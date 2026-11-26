"""Tests for the item tier views: trioforge.model.items.

``at_tier(item, tier, rules)`` turns a catalog item (a dict that validates against the catalog
schema) into an ``ItemVec`` at one upgrade tier. The tier rules are read from rules/rules.json:

* each stat is ``base + max(n, floor(base * n / 10))`` when the base is above zero (attack is the one stat that is
  not scaled: ``tier.unscaled_stats``, the game client's own calculation);
* a negative stat shrinks toward zero by the same amount a positive one grows, and never passes zero (``tier.negatives_scale``, the game client's own calculation);
* worn haste and the three regens add a flat amount per tier when the base is above zero;
* resists follow the stat rule;
* the weight, in tenths of a stone, falls by ``tier.weight_pct`` percent of the base a tier, rounded down, to a floor of
  0.1 stone;
* weapon damage rises by ``tier.weapon_damage_pct`` percent of the base a tier, rounded down, with no minimum step.

Every item below is invented. The expected numbers are written out by hand, so these tests do not
trust the module they check.
"""

import copy
import dataclasses
import json
import math
import re
import struct

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import solver_helpers as H
from trioforge import rules as rules_module
from trioforge.data.normalize import validate_item
from trioforge.model import items
from trioforge.model.items import ItemVec, WeaponVec, at_tier

RULES = rules_module.load()

CLASS_CODES = "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split()
STAT_KEYS = "AC STR STA AGI DEX WIS INT CHA HP MANA END ATK HPREG MANAREG ENDREG".split()
SCALED_KEYS = "AC STR STA AGI DEX WIS INT CHA HP MANA END".split()  # (ATK does not tier: T1)
UNSCALED_KEYS = ["ATK"]
REGEN_KEYS = "HPREG MANAREG ENDREG".split()


def item(**changes):
    """A schema-valid catalog item with an invented name; ``changes`` replace whole fields."""
    base = {
        "key": "w9001",
        "name": "Ring of Invented Tests",
        "wiki": {"pageid": 9001, "revid": 1, "title": "Ring of Invented Tests"},
        "slots": ["FINGER"],
        "classes": ["ALL"],
        "races": ["ALL"],
        "deity": None,
        "flags": [],
        "stats": {},
        "sv": {},
        "weight": 0.1,
        "size": "TINY",
        "item_type": None,
        "item_type_source": None,
        "weapon": None,
        "container_capacity": None,
        "instrument_mods": {},
        "effects": [],
        "required_level": None,
        "recommended_level": None,
        "sources": {"drops": [], "sold_by": [], "quests": [], "crafted": []},
        "categories": [],
        "era_tags": [],
        "lucy_img_id": None,
        "tier_rule": "drop",
        "parse_warnings": [],
        "parse_warnings_overflow": 0,
    }
    base.update(changes)
    return base


def weapon(skill="1H Slashing", dmg=20, delay=30, bonus=None):
    return {"skill": skill, "dmg": dmg, "delay": delay, "bonus": bonus}


def rules_with(changes):
    """The real rules with some values replaced: ``{rule id: new value}``."""
    data = json.loads(rules_module.RULES_PATH.read_text(encoding="utf-8"))
    for rule in data["rules"]:
        if rule["id"] in changes:
            rule["value"] = changes[rule["id"]]
    return rules_module.Rules(data)


def test_the_synthetic_items_are_valid_catalog_items():
    validate_item(item())
    validate_item(item(stats={"AC": 20, "HASTE": 41, "HPREG": 2}, sv={"FIRE": 5}, weight=10.0))
    validate_item(item(slots=["PRIMARY"], weapon=weapon("2H Blunt", 33, 40, 20)))
    validate_item(item(slots=["SECONDARY"], item_type="Shield", stats={"AC": 35}))


# ---- the numbers of the plan -----------------------------------------------------------------


@pytest.mark.parametrize("tier, expected", [(0, 20), (4, 28), (10, 40)])
def test_ac_20_scales_by_ten_percent_of_the_base_per_tier(tier, expected):
    assert at_tier(item(stats={"AC": 20}), tier, RULES).stats == {"AC": expected}


def test_a_small_base_gains_at_least_one_point_per_tier():
    assert at_tier(item(stats={"AC": 3}), 4, RULES).stats == {"AC": 7}


def test_the_rounding_of_ten_percent_goes_down():
    # 19 * 4 // 10 = 7 is above the +4 minimum; 9 * 4 // 10 = 3 is below it.
    assert at_tier(item(stats={"AC": 19}), 4, RULES).stats["AC"] == 19 + 7
    assert at_tier(item(stats={"AC": 9}), 4, RULES).stats["AC"] == 9 + 4


@pytest.mark.parametrize("tier", [0, 1, 2, 4, 10])
def test_item_attack_does_not_tier_whatever_the_tier(tier):
    """T1: the game client's own calculation never scales the attack of an item: a +4 or a +10 item's attack is its +0 value, while a stat beside it is scaled."""
    vec = at_tier(item(stats={"ATK": 10, "STR": 10, "AC": 3}), tier, RULES)
    assert vec.stats["ATK"] == 10
    assert vec.stats["STR"] == 10 + max(tier, 10 * tier // 10)
    assert vec.stats["AC"] == 3 + tier
    assert at_tier(item(stats={"ATK": 100}), tier, RULES).stats == {"ATK": 100}


def test_the_stats_that_do_not_tier_are_a_rule_and_the_model_refuses_one_it_does_not_know():
    assert RULES.get("tier.unscaled_stats") == ["ATK"]
    scaled_like_the_others = rules_with({"tier.unscaled_stats": []})
    assert at_tier(item(stats={"ATK": 10}), 4, scaled_like_the_others).stats == {"ATK": 14}  # (the rule is what keeps it still)
    both = rules_with({"tier.unscaled_stats": ["ATK", "STR"]})
    assert at_tier(item(stats={"ATK": 10, "STR": 10}), 4, both).stats == {"ATK": 10, "STR": 10}
    for bad in (["HASTE"], ["atk"], "ATK", [5]):
        with pytest.raises(ValueError, match="tier.unscaled_stats"):
            at_tier(item(stats={"ATK": 10}), 4, rules_with({"tier.unscaled_stats": bad}))


@pytest.mark.parametrize(
    "base, tier, expected",
    [(-2, 0, -2), (-2, 1, -1), (-2, 2, 0), (-2, 4, 0), (-20, 4, -12), (-5, 4, -1), (-1, 1, 0), (-100, 10, 0), (-30, 1, -27), (-9, 3, -6), (-15, 3, -11), (-40, 10, 0)],
)
def test_a_negative_stat_shrinks_toward_zero_by_the_amount_a_positive_one_grows_and_never_passes_zero(base, tier, expected):
    """T6: the client moves a negative stat toward zero by max(n, floor(|base| x n / 10)), never past zero: -2 is -1 at +1 and gone at +2, -20 is -12 at +4. Zero is dropped like any zero stat."""
    stats = at_tier(item(stats={"STR": base}), tier, RULES).stats
    assert stats.get("STR", 0) == expected and ("STR" in stats) == (expected != 0)
    assert at_tier(item(stats={"STR": -3, "STA": 10}), 10, RULES).stats == {"STA": 20}  # (the negative stat is gone at +10, the positive one has doubled)


def f32(x):
    """A number rounded to float32, as the client's arithmetic does it (the one rule, copied from the game client's own calculation: no program is imported)."""
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def client_stat(base, tier):
    """The client's value of a stat at the start of tier ``tier`` (experience 2^tier): ``base + (int)max(t, 0.1 t b)`` above zero, ``base + (int)min(-b, max(t, -0.1 t b))`` below it, in float32."""
    if tier == 0 or base == 0:
        return base
    t = f32(f32(math.log(2**tier)) / f32(math.log(2.0)))
    if base > 0:
        return base + int(max(f32(f32(t * f32(0.1)) * f32(base)), t))
    return base + int(min(f32(f32(base) * f32(-1.0)), max(f32(f32(t * f32(-0.1)) * f32(base)), t)))


def test_the_stat_rule_for_positive_and_negative_stats_is_the_clients_arithmetic_at_every_whole_tier():
    for base in range(-400, 401):
        for tier in range(11):
            assert at_tier(item(stats={"STR": base}), tier, RULES).stats.get("STR", 0) == client_stat(base, tier), (base, tier)
            assert at_tier(item(sv={"FIRE": base}), tier, RULES).sv.get("FIRE", 0) == client_stat(base, tier), (base, tier)


def test_worn_haste_rises_one_point_per_tier_and_is_not_among_the_stats():
    vec = at_tier(item(stats={"HASTE": 41, "AC": 5}), 5, RULES)
    assert vec.haste == 46
    assert "HASTE" not in vec.stats and vec.stats == {"AC": 5 + 5}


def test_an_item_without_haste_has_zero_haste():
    assert at_tier(item(stats={"AC": 5}), 7, RULES).haste == 0


@pytest.mark.parametrize("key", REGEN_KEYS)
def test_regen_rises_one_point_per_tier(key):
    assert at_tier(item(stats={key: 2}), 10, RULES).stats == {key: 12}
    assert at_tier(item(stats={key: 2}), 0, RULES).stats == {key: 2}


def test_haste_and_regen_follow_the_rules_not_a_constant():
    two_a_tier = rules_with({"haste.worn_per_tier": 2, "regen.per_tier": 3})
    vec = at_tier(item(stats={"HASTE": 10, "HPREG": 1}), 4, two_a_tier)
    assert vec.haste == 18 and vec.stats["HPREG"] == 13


def test_a_non_positive_haste_is_left_alone():
    assert at_tier(item(stats={"HASTE": -5}), 6, RULES).haste == -5


def test_resists_follow_the_stat_rule():
    vec = at_tier(item(sv={"FIRE": 20, "COLD": 3, "MAGIC": -4, "POISON": -20}), 4, RULES)
    assert vec.sv == {"FIRE": 28, "COLD": 7, "POISON": -12}  # (T6: the resist of -4 is gone at +4, the one of -20 is -12)


@pytest.mark.parametrize("weight, tier, expected", [(10.0, 0, 100), (10.0, 4, 64), (10.0, 10, 10), (3.0, 10, 3), (0.1, 10, 1)])
def test_weight_in_tenths_of_a_stone_falls_to_a_floor_of_one(weight, tier, expected):
    assert at_tier(item(weight=weight), tier, RULES).weight10 == expected


def test_weight_rounds_the_reduction_down_with_no_minimum_step():
    # 7.3 stones = 73 tenths: +4 takes 73 * 9 * 4 // 100 = 26 -> 47.
    assert at_tier(item(weight=7.3), 4, RULES).weight10 == 47
    # 1.5 stones = 15 tenths: +4 takes 15 * 9 * 4 // 100 = 5 -> 10; +1 takes 15 * 9 // 100 = 1 -> 14.
    assert at_tier(item(weight=1.5), 4, RULES).weight10 == 10
    assert at_tier(item(weight=1.5), 1, RULES).weight10 == 14
    # a small weight loses nothing until the percent adds up to a tenth: 0.2 stone is still 0.2 at +5
    assert at_tier(item(weight=0.2), 5, RULES).weight10 == 2


def test_a_weightless_item_stays_weightless_and_an_unknown_weight_is_flagged():
    zero = at_tier(item(weight=0), 6, RULES)
    assert (zero.weight10, zero.weight_known) == (0, True)
    unknown = at_tier(item(weight=None), 6, RULES)
    assert (unknown.weight10, unknown.weight_known) == (10, False)  # an unknown weight counts as 1.0 stone
    assert at_tier(item(weight=2.5), 0, RULES).weight_known is True


@pytest.mark.parametrize("tier", range(11))
def test_an_unknown_weight_counts_as_one_stone_at_every_tier_and_keeps_its_flag(tier):
    # the page gives no weight, so there is nothing for the tiers to reduce: 1.0 stone, for the Monk's worn weight
    vec = at_tier(item(weight=None), tier, RULES)
    assert (vec.weight10, vec.weight_known) == (10, False)


def test_an_unknown_weight_weighs_one_stone_in_the_monk_bonus_like_a_page_that_says_so():
    from trioforge.model import formulas as fm

    curve = fm.monk_curve(RULES, 50)  # the full bonus up to 17 whole stones, then the fade
    unknown = at_tier(item(slots=["CHEST"], weight=None, stats={"AC": 10}), 0, RULES)
    stated = at_tier(item(slots=["CHEST"], weight=1.0, stats={"AC": 10}), 0, RULES)
    heavy = at_tier(item(slots=["LEGS"], weight=17.5, stats={"AC": 5}), 0, RULES)
    assert (unknown.weight10, stated.weight10, heavy.weight10) == (10, 10, 175)
    assert (unknown.weight_known, stated.weight_known) == (False, True)
    assert fm.monk_bonus(50, heavy.weight10, curve) == 73  # 17 whole stones: still the full bonus
    faded = fm.monk_bonus(50, heavy.weight10 + unknown.weight10, curve)  # 18 whole stones: the fade has begun
    assert faded < 73 and faded == fm.monk_bonus(50, heavy.weight10 + stated.weight10, curve)


@pytest.mark.parametrize(
    ("races", "expected"),
    [
        (["ALL"], None),  # every race
        ([], frozenset()),  # a page that says Race: NONE: no race may wear it (not None, which is every race)
        (["HUM"], frozenset({"HUM"})),
        (["HUM", "ELF", "HEF", "HFL"], frozenset({"HUM", "ELF", "HEF", "HFL"})),
    ],
)
def test_the_race_restriction_is_a_set_of_races_or_none_for_every_race(races, expected):
    vec = at_tier(item(races=races), 0, RULES)
    assert vec.races == expected
    assert vec.races is None or isinstance(vec.races, frozenset)


@pytest.mark.parametrize("races", [["all"], ["All"], ["aLl"], ["HUM", "all"], ["all", "HUM", "ELF"], ["ALL", "ALL"]])
def test_all_is_every_race_in_any_case_whatever_else_is_listed(races):
    assert at_tier(item(races=races), 0, RULES).races is None


@pytest.mark.parametrize(
    "races",
    ["HUM", "ALL", "all", "", ["HUM", 1], ["HUM", None], [["HUM"]], [b"HUM"], ("HUM",), {"HUM"}, {"HUM": 1}, 5, True],
)
def test_races_that_are_not_a_list_of_strings_are_refused(races):
    with pytest.raises(ValueError, match="races must be a list"):
        items._races(races)
    with pytest.raises(ValueError, match="w9001: races must be a list"):  # at_tier names the item
        at_tier(item(races=races), 0, RULES)


def test_an_item_with_no_races_field_is_open_to_every_race():
    bare = item()
    del bare["races"]
    assert at_tier(bare, 0, RULES).races is None
    assert at_tier(item(races=None), 0, RULES).races is None


def test_a_weight_that_is_not_a_multiple_of_a_tenth_rounds_half_up():
    assert at_tier(item(weight=0.25), 0, RULES).weight10 == 3
    assert at_tier(item(weight=0.24), 0, RULES).weight10 == 2


# ---- weapons -------------------------------------------------------------------------------


def test_weapon_damage_ten_percent_a_tier_is_the_default():
    vec = at_tier(item(slots=["PRIMARY"], weapon=weapon(dmg=20, delay=30, bonus=7)), 4, RULES)
    assert vec.weapon == WeaponVec(skill="1H Slashing", dmg=28, delay=30, bonus=7, two_handed=False)


def test_weapon_damage_five_percent_a_tier_when_the_rule_says_five():
    five = rules_with({"tier.weapon_damage_pct": 5})
    vec = at_tier(item(slots=["PRIMARY"], weapon=weapon(dmg=20)), 4, five)
    assert vec.weapon.dmg == 24
    # the keyword does the same without a second rules object
    assert at_tier(item(slots=["PRIMARY"], weapon=weapon(dmg=20)), 4, RULES, weapon_pct=5).weapon.dmg == 24


def test_weapon_damage_has_no_minimum_step_a_tier():
    assert at_tier(item(slots=["PRIMARY"], weapon=weapon(dmg=3)), 4, RULES).weapon.dmg == 4  # was 7 with a point a tier


@pytest.mark.parametrize("dmg, tier, expected", [(20, 0, 20), (20, 1, 22), (45, 3, 58), (45, 10, 90), (100, 10, 200)])
def test_weapon_damage_ten_percent_rounded_down(dmg, tier, expected):
    # 45 * 3 * 10 // 100 = 13 (1350 / 100 rounded down); 45 * 10 * 10 // 100 = 45; 20 * 1 * 10 // 100 = 2
    assert at_tier(item(slots=["PRIMARY"], weapon=weapon(dmg=dmg)), tier, RULES).weapon.dmg == expected


def test_delay_and_the_listed_bonus_never_change():
    for tier in (0, 5, 10):
        vec = at_tier(item(slots=["PRIMARY"], weapon=weapon(dmg=30, delay=44, bonus=20)), tier, RULES)
        assert (vec.weapon.delay, vec.weapon.bonus) == (44, 20)
    assert at_tier(item(slots=["PRIMARY"], weapon=weapon(bonus=None)), 3, RULES).weapon.bonus is None


@pytest.mark.parametrize(
    "skill, two_handed",
    [
        ("2H Slashing", True), ("2H Blunt", True), ("2H Piercing", True), ("Two Hand Slashing", True),
        ("1H Slashing", False), ("Piercing", False), ("Hand to Hand", False), (None, False),
    ],
)
def test_two_handed_follows_the_skill(skill, two_handed):
    vec = at_tier(item(slots=["PRIMARY"], weapon=weapon(skill=skill)), 0, RULES)
    assert vec.weapon.two_handed is two_handed
    assert vec.weapon.skill == skill


def test_an_item_without_damage_and_delay_has_no_weapon():
    assert at_tier(item(), 0, RULES).weapon is None
    unrated = {"skill": "Brass Instruments", "dmg": None, "delay": None, "bonus": None}
    instrument = item(slots=["PRIMARY"], weapon=unrated)
    assert at_tier(instrument, 4, RULES).weapon is None


# ---- shields -------------------------------------------------------------------------------


def test_a_shield_is_flagged_from_its_type():
    shield = item(slots=["SECONDARY"], item_type="Shield", stats={"AC": 35})
    assert at_tier(shield, 0, RULES).is_shield is True
    assert at_tier(shield, 0, RULES).weapon is None


def test_a_shield_has_no_weapon_even_when_its_page_gives_a_damage_and_a_delay():
    shield = item(slots=["SECONDARY"], item_type="Shield", stats={"AC": 12}, weapon=weapon(skill="1H Blunt", dmg=3, delay=30))
    vec = at_tier(shield, 0, RULES)
    assert vec.is_shield is True and vec.weapon is None


@pytest.mark.parametrize("kind", ["Shield", "shield", "SHIELD"])
def test_a_shield_is_flagged_from_its_type_in_any_case(kind):
    assert at_tier(item(slots=["SECONDARY"], item_type=kind, stats={"AC": 35}), 0, RULES).is_shield is True


def test_the_type_is_the_only_thing_that_makes_a_shield_a_skill_does_not():
    # the catalog builder fills item_type; the model reads that field and nothing else
    held = item(slots=["SECONDARY"], stats={"AC": 12}, weapon=weapon(skill="Shield", dmg=3, delay=30))
    assert at_tier(held, 0, RULES).is_shield is False


def test_a_non_weapon_with_armor_class_in_the_secondary_slot_alone_is_not_a_shield():
    # a slot and an armor class make a focus crystal, an orb, a totem or an instrument too: none of them is a shield
    for kind in (None, "Buckler", "Shield Augment"):
        held = item(slots=["SECONDARY"], item_type=kind, stats={"AC": 12})
        assert at_tier(held, 0, RULES).is_shield is False, kind


@pytest.mark.parametrize(
    "changes",
    [
        dict(slots=["SECONDARY"], stats={"WIS": 5}),  # a held item: no armor class
        dict(slots=["SECONDARY"], stats={"AC": 12, "WIS": 5}),  # a held item with armor class and no type
        dict(slots=["SECONDARY"], stats={"AC": 8}, categories=["Focus Items", "Secondary"]),  # a focus crystal
        dict(slots=["SECONDARY"], stats={"AC": 8}, categories=["Bard Instrument"]),  # an instrument
        dict(slots=["PRIMARY", "SECONDARY"], stats={"AC": 3}),  # also fits the main hand
        dict(slots=["PRIMARY", "SECONDARY"], weapon=weapon(dmg=3, delay=24), stats={"AC": 3}),  # a weapon
        dict(slots=["CHEST"], stats={"AC": 30}),
        dict(slots=["PRIMARY"], item_type="Shield", stats={"AC": 30}),  # not worn in the off hand
    ],
)
def test_items_that_are_not_shields(changes):
    assert at_tier(item(**changes), 2, RULES).is_shield is False


# ---- identity fields -----------------------------------------------------------------------


def test_identity_fields_are_copied_and_the_sets_are_frozen():
    raw = item(
        key="w77", name="Cloak of Invented Winds", slots=["BACK", "FACE"], classes=["WAR", "PAL"],
        deity=["Karana", "Tunare"], flags=["lore", "magic"],
    )
    vec = at_tier(raw, 3, RULES)
    assert (vec.key, vec.name, vec.tier) == ("w77", "Cloak of Invented Winds", 3)
    assert vec.slots == frozenset({"BACK", "FACE"}) and isinstance(vec.slots, frozenset)
    assert vec.classes == frozenset({"WAR", "PAL"}) and isinstance(vec.classes, frozenset)
    assert vec.deity == frozenset({"Karana", "Tunare"}) and isinstance(vec.deity, frozenset)
    assert vec.lore is True


def test_all_classes_expands_to_the_sixteen_codes():
    assert at_tier(item(classes=["ALL"]), 0, RULES).classes == frozenset(CLASS_CODES)


def test_no_deity_restriction_is_none_and_lore_defaults_to_false():
    vec = at_tier(item(), 0, RULES)
    assert vec.deity is None and vec.lore is False


def test_zero_stats_are_dropped():
    assert at_tier(item(stats={"AC": 0, "STR": 5}), 1, RULES).stats == {"STR": 6}


def test_the_catalog_item_is_not_changed():
    raw = item(stats={"AC": 20, "HASTE": 10}, sv={"FIRE": 4}, slots=["PRIMARY"], weapon=weapon())
    before = copy.deepcopy(raw)
    at_tier(raw, 9, RULES)
    assert raw == before


def test_an_item_vec_is_frozen_hashable_and_compares_by_value():
    raw = item(stats={"AC": 20})
    first, second = at_tier(raw, 4, RULES), at_tier(raw, 4, RULES)
    assert first == second and hash(first) == hash(second)
    assert first != at_tier(raw, 5, RULES)
    assert len({first, second, at_tier(raw, 5, RULES)}) == 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.tier = 9


# ---- refusals ------------------------------------------------------------------------------


@pytest.mark.parametrize("tier", [-1, 11, 100, True, 2.0, "4", None])
def test_a_tier_must_be_a_whole_number_from_zero_to_ten(tier):
    with pytest.raises((TypeError, ValueError)):
        at_tier(item(stats={"AC": 1}), tier, RULES)


@pytest.mark.parametrize("value", [True, False, "grow", "toward zero by n, never past zero"])
def test_a_rules_file_that_scales_negative_stats_another_way_is_refused_not_guessed(value):
    with pytest.raises(ValueError, match="negatives_scale"):
        at_tier(item(), 1, rules_with({"tier.negatives_scale": value}))


def test_a_weapon_rate_other_than_five_or_ten_is_refused():
    with pytest.raises(ValueError, match="weapon"):
        at_tier(item(), 1, rules_with({"tier.weapon_damage_pct": 7}))
    with pytest.raises(ValueError, match="weapon"):
        at_tier(item(), 1, RULES, weapon_pct=7)


def test_a_changed_stat_rule_text_is_refused():
    with pytest.raises(ValueError, match="stat_rule"):
        at_tier(item(), 1, rules_with({"tier.stat_rule": "base + n"}))


def test_an_unknown_stat_is_refused_rather_than_dropped():
    with pytest.raises(ValueError, match="BOGUS"):
        at_tier(item(stats={"BOGUS": 3}), 1, RULES)


def test_the_tier_rules_on_disk_say_what_the_module_implements():
    # The same facts, read straight from the file: if one changes, this fails before a pick does.
    assert RULES.get("tier.stat_rule") == "base + max(n, floor(base*n/10))"
    assert RULES.get("tier.negatives_scale") == "toward zero by max(n, floor(|base|*n/10)), never past zero"
    assert RULES.get("tier.weapon_damage_pct") == 10
    assert RULES.get("haste.worn_per_tier") == 1 and RULES.get("regen.per_tier") == 1
    assert RULES.get("tier.weight_floor") == 0.1 and RULES.get("tier.weight_pct") == 9


# ---- slots ---------------------------------------------------------------------------------


def test_slot_instances_are_the_twenty_two_places_a_kit_has():
    assert items.SLOT_INSTANCES == tuple(
        (
            "HEAD FACE EAR EAR NECK SHOULDERS ARMS BACK WRIST WRIST HANDS FINGER FINGER CHEST LEGS FEET WAIST RANGE "
            "ANY ANY PRIMARY SECONDARY"
        ).split()
    )
    assert len(items.SLOT_INSTANCES) == 22
    assert dict(items.SLOT_GROUPS) == {
        "HEAD": 1, "FACE": 1, "EAR": 2, "NECK": 1, "SHOULDERS": 1, "ARMS": 1, "BACK": 1, "WRIST": 2, "HANDS": 1,
        "FINGER": 2, "CHEST": 1, "LEGS": 1, "FEET": 1, "WAIST": 1, "RANGE": 1, "ANY": 2, "PRIMARY": 1, "SECONDARY": 1,
    }


# ---- properties ----------------------------------------------------------------------------

stat_dicts = st.dictionaries(st.sampled_from(STAT_KEYS), st.integers(min_value=0, max_value=400), max_size=8)
SCHOOLS = "FIRE COLD MAGIC POISON DISEASE CORRUPTION".split()
sv_dicts = st.dictionaries(st.sampled_from(SCHOOLS), st.integers(0, 150), max_size=4)


@settings(max_examples=200, deadline=None)
@given(
    stats=stat_dicts,
    sv=sv_dicts,
    haste=st.integers(min_value=0, max_value=60),
    weight=st.integers(min_value=0, max_value=3000).map(lambda tenths: tenths / 10),
    dmg=st.integers(min_value=1, max_value=400),
    low=st.integers(min_value=0, max_value=10),
    high=st.integers(min_value=0, max_value=10),
)
def test_every_stat_is_monotone_in_the_tier_for_a_non_negative_base(stats, sv, haste, weight, dmg, low, high):
    low, high = sorted((low, high))
    raw = item(
        slots=["PRIMARY"], stats={**{k: v for k, v in stats.items() if v}, **({"HASTE": haste} if haste else {})},
        sv={k: v for k, v in sv.items() if v}, weight=weight, weapon=weapon(dmg=dmg),
    )
    first, second = at_tier(raw, low, RULES), at_tier(raw, high, RULES)
    for key, value in first.stats.items():
        assert value <= second.stats[key]
    for key, value in first.sv.items():
        assert value <= second.sv[key]
    assert first.haste <= second.haste
    assert first.weapon.dmg <= second.weapon.dmg
    assert first.weight10 >= second.weight10
    # tier 0 is the catalog value itself
    zero = at_tier(raw, 0, RULES)
    assert zero.stats == {k: v for k, v in raw["stats"].items() if k != "HASTE"}
    assert zero.haste == raw["stats"].get("HASTE", 0)


@settings(max_examples=100, deadline=None)
@given(stats=stat_dicts, tier=st.integers(min_value=0, max_value=10))
def test_a_scaled_stat_never_loses_value_and_gains_at_least_the_tier(stats, tier):
    raw = item(stats={k: v for k, v in stats.items() if v})
    vec = at_tier(raw, tier, RULES)
    for key, base in raw["stats"].items():
        if key in SCALED_KEYS:
            assert vec.stats[key] >= base + tier
            assert vec.stats[key] >= base + base * tier // 10
        elif key in UNSCALED_KEYS:
            assert vec.stats[key] == base
        else:
            assert vec.stats[key] == base + tier


def test_the_module_exports_what_the_plan_names():
    assert {"ItemVec", "WeaponVec", "at_tier", "SLOT_INSTANCES"} <= set(items.__all__)
    assert isinstance(at_tier(item(), 0, RULES), ItemVec)


# ---- real data -----------------------------------------------------------------------------


SHIELD_WORD = re.compile(r"shield|buckler|aegis|bulwark|targe", re.IGNORECASE)  # written out: not the catalog builder's constant


@H.slow
def test_a_buckler_with_a_focus_effect_is_a_shield_and_the_held_items_around_it_are_not():
    by_key = {raw["key"]: raw for raw in H.catalog_items()}
    buckler = by_key["w57374"]  # Spiked Buckler: AC 10 and an Improved Damage I focus, so the wiki files it under Focus Items
    assert buckler["name"] == "Spiked Buckler" and "Focus Items" in buckler["categories"]
    assert at_tier(buckler, 0, RULES).is_shield
    held = [raw for raw in by_key.values() if set(raw["categories"]) & {"Focus Items", "Bard Instrument"} and raw["slots"] == ["SECONDARY"]]
    assert {raw["name"] for raw in held if (raw["stats"].get("AC") or 0) > 0 and not SHIELD_WORD.search(raw["name"])} >= {
        "A Shimmering Orb", "Rokyls Channelling Crystal", "Lyendlln's Lute",
    }  # fmt: skip
    assert not any(at_tier(raw, 0, RULES).is_shield for raw in held if not SHIELD_WORD.search(raw["name"]))


@H.slow
def test_in_the_real_catalog_exactly_the_items_typed_as_shields_are_shields(capsys):
    shields = []
    for raw in H.catalog_items():
        typed = "SECONDARY" in raw["slots"] and (raw["item_type"] or "").lower() == "shield"
        vec = at_tier(raw, 0, RULES)
        assert vec.is_shield is typed, raw["key"]
        assert not (vec.is_shield and vec.weapon is not None), raw["key"]
        if set(raw["categories"]) & {"Focus Items", "Bard Instrument"} and not SHIELD_WORD.search(raw["name"]):
            # held items are no shields, whatever their armor class; a buckler with a focus effect is a shield
            assert not vec.is_shield, raw["key"]
        shields.append(raw["evidence"]["level"]) if vec.is_shield else None
    assert shields
    with capsys.disabled():
        counts = {level: shields.count(level) for level in sorted(set(shields))}
        print(f"\nitems classed as shields in the catalog: {len(shields)} {counts}")
