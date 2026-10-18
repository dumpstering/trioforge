"""Tests for the roles of a trio and their weights: ``trioforge.model.roles``.

The role rules: Balanced is always offered; Tank when the trio has a Warrior, Paladin or Shadow Knight; Melee
when any class has the Offensive stance; Caster when any class casts; a trio with only one of the three keeps
Balanced alone, with that role's weights. The weights come from the
templates of ``roles.templates`` (Balanced is their arithmetic mean), with the resist weight spread over the five
schools, the regen weights worth ``10 x T x`` the resource they return, the weapon damage weight worth the rule
``weapons.damage_weight`` times the template's ATK weight (0 for the Caster), and no mana weight for a trio with no
mana class. Every class list below is written out here on purpose, so these tests do not trust the module they check.
"""

import copy
import itertools
import json
from pathlib import Path

import pytest

from trioforge.classes import CLASS_CODES
from trioforge.model import roles, weapons
from trioforge.model.formulas import SCHOOLS, WEIGHT_KEYS
from trioforge.rules import Rules
from trioforge.rules import load as load_rules

REPO = Path(__file__).resolve().parents[2]
RULES = load_rules()
RAW = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))
TRIOS = list(itertools.combinations(CLASS_CODES, 3))

TANKS = {"WAR", "PAL", "SHD"}
MELEE = {"BER", "BRD", "BST", "MNK", "PAL", "RNG", "ROG", "SHD", "WAR"}
CASTERS = {"CLR", "DRU", "SHM", "NEC", "WIZ", "MAG", "ENC"}
MANA_CLASSES = {"PAL", "RNG", "BST", "CLR", "SHM", "DRU", "SHD", "BRD", "WIZ", "ENC", "NEC", "MAG"}

# the three templates of roles.templates, with the five schools written out
TANK = {"HP": 1, "AC": 6, "MANA": 0.5, "ATK": 2, "DEX": 0.1, "HASTE": 1.5, "END": 0.5, "CHA": 0.05}
MELEE_T = {"HP": 1.3, "AC": 1.5, "MANA": 0.5, "ATK": 3, "DEX": 0.8, "HASTE": 3, "END": 0.3, "CHA": 0.05}
CASTER = {"HP": 1, "AC": 1.2, "MANA": 4.0, "ATK": 0.3, "DEX": 0.1, "HASTE": 0, "END": 0.05, "CHA": 0.05}
SV = {"tank": 0.4, "melee": 0.2, "caster": 0.4}


def rules_with(**changes):
    """The real rules with the value of some rules replaced (``rules_with(**{"roles.templates": ...})``)."""
    data = copy.deepcopy(RAW)
    seen = set()
    for rule in data["rules"]:
        if rule["id"] in changes:
            rule["value"] = changes[rule["id"]]
            seen.add(rule["id"])
    assert seen == set(changes), "a rule id that the real file does not have"
    return Rules(data)


def templates_with(**changes):
    """The real templates with whole templates replaced or added."""
    templates = copy.deepcopy(RULES.get("roles.templates"))
    templates.update(changes)
    return rules_with(**{"roles.templates": templates})


# ---- the vocabulary -------------------------------------------------------------------------------------


def test_the_roles_are_in_the_order_the_weapons_module_uses():
    assert roles.ROLES == ("balanced", "tank", "melee", "caster")
    assert roles.ROLES == weapons.ROLES


def test_the_class_lists_are_the_role_rules_and_cover_every_class_once():
    assert roles.TANK_CLASSES == TANKS
    assert roles.MELEE_CLASSES == MELEE
    assert roles.CASTER_CLASSES == CASTERS == weapons.CASTER_CLASSES
    assert MELEE | CASTERS == set(CLASS_CODES) and not MELEE & CASTERS  # every class has an Offensive stance or casts
    assert TANKS <= MELEE


# ---- which roles a trio is offered ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trio", "expected"),
    [
        (("PAL", "MNK", "BER"), ["balanced", "tank", "melee"]),
        (("WIZ", "MAG", "ENC"), ["balanced"]),  # one role only: Balanced carries the Caster weights
        (("SHD", "CLR", "SHM"), ["balanced", "tank", "melee", "caster"]),
        (("MNK", "ROG", "BER"), ["balanced"]),  # Melee alone, no tank
        (("BRD", "RNG", "BST"), ["balanced"]),
        (("CLR", "MNK", "ROG"), ["balanced", "melee", "caster"]),
        (("WAR", "PAL", "SHD"), ["balanced", "tank", "melee"]),
        (("WAR", "CLR", "DRU"), ["balanced", "tank", "melee", "caster"]),
    ],
)
def test_roles_for_the_examples(trio, expected):
    assert roles.roles_for(trio) == expected


def test_the_order_of_the_trio_does_not_change_its_roles():
    assert roles.roles_for(("BER", "MNK", "PAL")) == roles.roles_for(["PAL", "MNK", "BER"])


@pytest.mark.parametrize(
    "trio",
    [("PAL", "MNK"), ("PAL", "MNK", "BER", "WAR"), ("PAL", "PAL", "MNK"), ("PAL", "MNK", "XXX"), "PALMNKBER", None],
)
def test_a_trio_must_be_three_different_class_codes(trio):
    with pytest.raises(ValueError, match="trio"):
        roles.roles_for(trio)
    with pytest.raises(ValueError, match="trio"):
        roles.weights_for(trio, "balanced", RULES)


def test_the_role_rules_hold_for_all_560_trios():
    assert len(TRIOS) == 560
    for trio in TRIOS:
        templates = [
            name
            for name, present in (
                ("tank", TANKS & set(trio)), ("melee", MELEE & set(trio)), ("caster", CASTERS & set(trio))
            )
            if present
        ]
        assert templates, trio  # every trio can play something
        assert roles.roles_for(trio) == ["balanced", *(templates if len(templates) > 1 else [])], trio


# ---- the weights ---------------------------------------------------------------------------------------


def expected(template, school_weight, *, dmg, mana=True, minutes=3):
    """The weights of one template: five schools, the regen weights worth 10 x T x what they return, and the weapon
    damage weight ``dmg`` (the rule times the template's ATK weight, 0 for the Caster)."""
    result = dict(template)
    result["DMG"] = dmg
    if not mana:
        result["MANA"] = 0
    for school in SCHOOLS:
        result[f"SV_{school}"] = school_weight
    result["HPREG"] = 10 * minutes * result["HP"]
    result["MANAREG"] = 10 * minutes * result["MANA"]
    result["ENDREG"] = 10 * minutes * result["END"]
    return result


def test_the_tank_and_melee_weights_are_their_templates():
    trio = ("PAL", "MNK", "BER")
    assert roles.weights_for(trio, "tank", RULES) == pytest.approx(expected(TANK, SV["tank"], dmg=1200))
    assert roles.weights_for(trio, "melee", RULES) == pytest.approx(expected(MELEE_T, SV["melee"], dmg=1800))
    assert roles.weights_for(("SHD", "CLR", "SHM"), "caster", RULES) == pytest.approx(
        expected(CASTER, SV["caster"], dmg=0)
    )


def test_balanced_is_the_mean_of_the_templates_the_trio_can_play():
    weights = roles.weights_for(("PAL", "MNK", "BER"), "balanced", RULES)
    assert weights["AC"] == (6 + 1.5) / 2 == 3.75
    assert weights == pytest.approx(
        {
            "HP": 1.15, "AC": 3.75, "MANA": 0.5, "ATK": 2.5, "DEX": 0.45, "HASTE": 2.25, "END": 0.4, "CHA": 0.05,
            "DMG": 1500,  # the mean of Tank (600 x 2) and Melee (600 x 3)
            **dict.fromkeys((f"SV_{school}" for school in SCHOOLS), 0.3),
            "HPREG": 34.5, "MANAREG": 15, "ENDREG": 12,
        }
    )  # fmt: skip
    three = roles.weights_for(("SHD", "CLR", "SHM"), "balanced", RULES)
    assert three["AC"] == pytest.approx((6 + 1.5 + 1.2) / 3)
    assert three["MANA"] == pytest.approx((0.5 + 0.5 + 4.0) / 3)
    assert three["HASTE"] == pytest.approx((1.5 + 3 + 0) / 3)


def test_balanced_of_a_trio_with_one_role_is_that_roles_weights():
    assert roles.weights_for(("WIZ", "MAG", "ENC"), "balanced", RULES) == pytest.approx(
        expected(CASTER, SV["caster"], dmg=0)
    )
    assert roles.weights_for(("MNK", "ROG", "BER"), "balanced", RULES) == pytest.approx(
        expected(MELEE_T, SV["melee"], dmg=1800, mana=False)
    )


def test_a_role_the_trio_is_not_offered_has_no_weights():
    for trio, role in [
        (("WIZ", "MAG", "ENC"), "tank"),
        (("WIZ", "MAG", "ENC"), "melee"),
        (("MNK", "ROG", "BER"), "melee"),  # merged into Balanced: the page shows Balanced only
        (("PAL", "MNK", "BER"), "caster"),
        (("PAL", "MNK", "BER"), "healer"),
        (("PAL", "MNK", "BER"), None),
    ]:
        with pytest.raises(ValueError, match="role"):
            roles.weights_for(trio, role, RULES)


def test_the_resist_weight_is_spread_over_the_five_schools_and_no_bare_sv_key_is_left():
    weights = roles.weights_for(("PAL", "MNK", "BER"), "tank", RULES)
    assert "SV" not in weights
    assert [weights[f"SV_{school}"] for school in SCHOOLS] == [0.4] * 5
    assert "SV_CORRUPTION" not in weights  # never scored


def test_regen_weights_are_ten_ticks_a_minute_times_the_window_times_the_resource_weight():
    trio = ("PAL", "MNK", "BER")
    assert roles.weights_for(trio, "tank", RULES)["HPREG"] == 10 * 3 * 1  # regen.value_minutes is 3
    longer = roles.weights_for(trio, "melee", rules_with(**{"regen.value_minutes": 5}))
    assert longer["HPREG"] == pytest.approx(10 * 5 * 1.3)
    assert longer["MANAREG"] == pytest.approx(10 * 5 * 0.5)
    assert longer["ENDREG"] == pytest.approx(10 * 5 * 0.3)
    none = roles.weights_for(trio, "melee", rules_with(**{"regen.value_minutes": 0}))
    assert none["HPREG"] == none["MANAREG"] == none["ENDREG"] == 0


@pytest.mark.parametrize("minutes", [-1, True, "3"])
def test_a_regen_window_that_is_not_a_non_negative_number_is_refused(minutes):
    rules = rules_with(**{"regen.value_minutes": minutes})
    with pytest.raises(ValueError, match="regen.value_minutes"):
        roles.weights_for(("PAL", "MNK", "BER"), "tank", rules)


def test_a_trio_with_no_mana_class_gets_no_mana_or_mana_regen_weight():
    for trio in [("WAR", "MNK", "ROG"), ("MNK", "ROG", "BER")]:
        for role in roles.roles_for(trio):
            weights = roles.weights_for(trio, role, RULES)
            assert weights["MANA"] == 0 and weights["MANAREG"] == 0, (trio, role)
            assert weights["HP"] > 0 and weights["ENDREG"] > 0  # the other currencies are untouched
    # one mana class is enough
    assert roles.weights_for(("WAR", "MNK", "PAL"), "tank", RULES)["MANA"] == 0.5


def test_mana_is_weighted_exactly_when_a_class_of_the_trio_has_a_mana_pool():
    for trio in TRIOS:
        for role in roles.roles_for(trio):
            weights = roles.weights_for(trio, role, RULES)
            assert (weights["MANA"] > 0) == bool(MANA_CLASSES & set(trio)), (trio, role)
            assert (weights["MANAREG"] > 0) == bool(MANA_CLASSES & set(trio)), (trio, role)


def test_the_caller_can_say_whether_mana_is_reachable():
    assert roles.weights_for(("WAR", "MNK", "ROG"), "tank", RULES, mana_reachable=True)["MANA"] == 0.5
    off = roles.weights_for(("PAL", "MNK", "BER"), "tank", RULES, mana_reachable=False)
    assert off["MANA"] == 0 and off["MANAREG"] == 0


def test_every_weight_of_every_role_of_every_trio_is_a_known_non_negative_number():
    for trio in TRIOS:
        for role in roles.roles_for(trio):
            weights = roles.weights_for(trio, role, RULES)
            assert set(weights) <= WEIGHT_KEYS, (trio, role)
            assert all(type(v) in (int, float) and v >= 0 for v in weights.values()), (trio, role)
            assert {"HP", "AC", "MANA", "ATK", "DEX", "HASTE", "END", "CHA", "HPREG", "MANAREG", "ENDREG"} <= set(weights)


def test_balanced_is_the_arithmetic_mean_of_the_roles_for_every_trio():
    for trio in TRIOS:
        offered = roles.roles_for(trio)
        if len(offered) == 1:
            continue
        balanced = roles.weights_for(trio, "balanced", RULES)
        singles = [roles.weights_for(trio, role, RULES) for role in offered[1:]]
        for key, value in balanced.items():
            assert value == pytest.approx(sum(single[key] for single in singles) / len(singles)), (trio, key)


def test_weights_are_returned_as_a_new_dict_each_time():
    first = roles.weights_for(("PAL", "MNK", "BER"), "tank", RULES)
    first["AC"] = 99
    assert roles.weights_for(("PAL", "MNK", "BER"), "tank", RULES)["AC"] == 6


# ---- the weapon damage weight ----------------------------------------------------------------------------
#
# weapons.damage_weight is the HP-equivalents of one damage-index point per unit of a template's ATK weight, so the
# DMG weight of a template is that number times the template's ATK weight (Tank 2, Melee 3). The Caster template
# scores no weapon damage and carries 0 whatever its ATK weight is. Balanced is the mean of the templates the trio
# can play, like every other weight.

DAMAGE_WEIGHT = 600  # weapons.damage_weight in rules/rules.json (written out here; test_rules.py pins the file)


def test_the_real_rules_weigh_a_weapon_at_the_damage_weight_times_the_atk_weight_of_the_template():
    trio = ("PAL", "MNK", "BER")
    assert RULES.get("weapons.damage_weight") == DAMAGE_WEIGHT
    assert roles.weights_for(trio, "melee", RULES)["DMG"] == DAMAGE_WEIGHT * 3 == 1800  # the Melee ATK weight is 3
    assert roles.weights_for(trio, "tank", RULES)["DMG"] == DAMAGE_WEIGHT * 2 == 1200  # the Tank ATK weight is 2
    assert roles.weights_for(trio, "balanced", RULES)["DMG"] == (1200 + 1800) / 2 == 1500
    three = ("SHD", "CLR", "SHM")
    assert roles.weights_for(three, "caster", RULES)["DMG"] == 0
    assert roles.weights_for(three, "balanced", RULES)["DMG"] == (1200 + 1800 + 0) / 3 == 1000
    assert roles.weights_for(("WIZ", "MAG", "ENC"), "balanced", RULES)["DMG"] == 0  # the Caster template alone
    assert roles.weights_for(("MNK", "ROG", "BER"), "balanced", RULES)["DMG"] == 1800  # the Melee template alone


def test_the_damage_weight_of_every_role_of_every_trio_is_the_mean_over_its_templates():
    scoring = {"tank": TANK["ATK"], "melee": MELEE_T["ATK"]}  # the Caster template (ATK 0.3) scores no damage at all
    for trio in TRIOS:
        templates = [
            name
            for name, present in (
                ("tank", TANKS & set(trio)), ("melee", MELEE & set(trio)), ("caster", CASTERS & set(trio))
            )
            if present
        ]
        for role in roles.roles_for(trio):
            names = templates if role == "balanced" else [role]
            scored = sum(DAMAGE_WEIGHT * scoring[name] for name in names if name in scoring)
            assert roles.weights_for(trio, role, RULES)["DMG"] == scored / len(names), (trio, role)


def test_with_no_damage_weight_in_the_rules_no_damage_weight_is_set():
    # A rules file whose weapons.damage_weight is null (legal: the rule is open) still works as it did before the
    # weight was defined: no DMG key at all, so weapons are chosen for their stats alone, and nothing else changes.
    rules = rules_with(**{"weapons.damage_weight": None})
    assert rules.get("weapons.damage_weight") is None
    for trio in [("SHD", "CLR", "SHM"), ("PAL", "MNK", "BER"), ("WIZ", "MAG", "ENC"), ("MNK", "ROG", "BER")]:
        for role in roles.roles_for(trio):
            plain = roles.weights_for(trio, role, rules)
            assert "DMG" not in plain, (trio, role)
            assert plain == {k: v for k, v in roles.weights_for(trio, role, RULES).items() if k != "DMG"}, (trio, role)


def test_a_damage_weight_in_the_rules_is_multiplied_by_the_atk_weight_of_each_template_and_not_the_caster():
    rules = rules_with(**{"weapons.damage_weight": 5})
    trio = ("SHD", "CLR", "SHM")
    assert roles.weights_for(trio, "tank", rules)["DMG"] == 5 * 2
    assert roles.weights_for(trio, "melee", rules)["DMG"] == 5 * 3
    assert roles.weights_for(trio, "caster", rules)["DMG"] == 0
    assert roles.weights_for(trio, "balanced", rules)["DMG"] == pytest.approx(25 / 3)
    assert roles.weights_for(("PAL", "MNK", "BER"), "balanced", rules)["DMG"] == 12.5
    assert roles.weights_for(("WIZ", "MAG", "ENC"), "balanced", rules)["DMG"] == 0


def test_the_damage_weight_follows_the_atk_weight_of_the_template_and_ignores_the_casters():
    templates = copy.deepcopy(RULES.get("roles.templates"))
    templates["melee"]["ATK"] = 4
    templates["caster"]["ATK"] = 5  # a Caster stick scores nothing, whatever the template's ATK weight
    rules = rules_with(**{"roles.templates": templates})
    trio = ("SHD", "CLR", "SHM")
    assert roles.weights_for(trio, "melee", rules)["DMG"] == DAMAGE_WEIGHT * 4
    assert roles.weights_for(trio, "tank", rules)["DMG"] == DAMAGE_WEIGHT * 2
    assert roles.weights_for(trio, "caster", rules)["DMG"] == 0
    assert roles.weights_for(trio, "balanced", rules)["DMG"] == (1200 + 2400 + 0) / 3
    assert roles.weights_for(("WIZ", "MAG", "ENC"), "balanced", rules)["DMG"] == 0
    templates["melee"]["ATK"] = 0  # a template that values no ATK values no weapon damage either
    free = rules_with(**{"roles.templates": templates})
    assert roles.weights_for(trio, "melee", free)["DMG"] == 0


def test_the_damage_weight_is_worked_in_exact_fractions_and_rounded_once():
    rules = rules_with(**{"weapons.damage_weight": 0.1})
    assert 0.1 * 3 != 0.3  # in floats the product would be 0.30000000000000004
    assert roles.weights_for(("PAL", "MNK", "BER"), "melee", rules)["DMG"] == 0.3


@pytest.mark.parametrize("value", [-1, True, "5", [5]])
def test_a_damage_weight_that_is_not_null_or_a_non_negative_number_is_refused(value):
    rules = rules_with(**{"weapons.damage_weight": value})
    with pytest.raises(ValueError, match="weapons.damage_weight"):
        roles.weights_for(("PAL", "MNK", "BER"), "tank", rules)


# ---- bad templates fail closed ---------------------------------------------------------------------------


def test_a_negative_template_weight_is_refused():
    rules = templates_with(tank={**RULES.get("roles.templates")["tank"], "AC": -1})
    with pytest.raises(ValueError, match="tank.*AC"):
        roles.weights_for(("PAL", "MNK", "BER"), "tank", rules)


@pytest.mark.parametrize("bad", [True, "6", None])
def test_a_template_weight_that_is_not_a_number_is_refused(bad):
    rules = templates_with(tank={**RULES.get("roles.templates")["tank"], "AC": bad})
    with pytest.raises(ValueError, match="tank.*AC"):
        roles.weights_for(("PAL", "MNK", "BER"), "tank", rules)


def test_a_template_with_an_unknown_or_missing_key_is_refused():
    tank = RULES.get("roles.templates")["tank"]
    extra = templates_with(tank={**tank, "FOO": 1})
    short = templates_with(tank={key: value for key, value in tank.items() if key != "CHA"})
    with pytest.raises(ValueError, match="FOO"):
        roles.weights_for(("PAL", "MNK", "BER"), "tank", extra)
    with pytest.raises(ValueError, match="CHA"):
        roles.weights_for(("PAL", "MNK", "BER"), "tank", short)


def test_a_missing_template_is_refused():
    templates = copy.deepcopy(RULES.get("roles.templates"))
    del templates["melee"]
    rules = rules_with(**{"roles.templates": templates})
    with pytest.raises(ValueError, match="melee"):
        roles.weights_for(("PAL", "MNK", "BER"), "balanced", rules)
