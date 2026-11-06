"""Tests for weapon setups and the per-hand damage index.

The functions read an item only through a few attributes (``weapon`` with ``dmg``, ``delay``, ``bonus``,
``two_handed``; ``is_shield``; ``classes``; ``haste``) and a profile through ``haste_cap`` and ``spell_haste``,
so the tests use small stand-ins with invented names. The skill caps come from the committed
``derived/client/skillcaps.json``, laid out as the tables module will lay them out: ``(class, skill, level)``.
"""

import json
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trioforge.classes import CLASS_CODES
from trioforge.model import weapons as wp
from trioforge.rules import load as load_rules

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES = load_rules()


@cache
def real_tables():
    data = json.loads((REPO_ROOT / "derived" / "client" / "skillcaps.json").read_text(encoding="utf-8"))
    names = {int(key): name for key, name in data["skill_names"].items()}
    caps = {
        (CLASS_CODES[row["class"] - 1], names[row["skill"]], row["level"]): row["cap"]
        for row in data["rows"]
        if row["skill"] in names
    }
    return SimpleNamespace(skillcap=caps, rules=RULES)


@dataclass(frozen=True)
class FakeWeapon:
    skill: str
    dmg: int | None
    delay: int | None
    bonus: int | None
    two_handed: bool


@dataclass(frozen=True)
class FakeItem:
    key: str
    weapon: FakeWeapon | None
    is_shield: bool
    classes: frozenset
    haste: int
    slots: frozenset


def weapon(dmg, delay, *, skill="1H Slashing", bonus=None, two_handed=False):
    return FakeWeapon(skill=skill, dmg=dmg, delay=delay, bonus=bonus, two_handed=two_handed)


def item(key, *, weapon=None, is_shield=False, classes=("ALL",), haste=0, slots=("PRIMARY",)):
    return FakeItem(
        key=key, weapon=weapon, is_shield=is_shield, classes=frozenset(classes), haste=haste, slots=frozenset(slots)
    )


# ---- which setups a trio has ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "trio", [("SHD", "CLR", "SHM"), ("WIZ", "MAG", "ENC"), ("PAL", "CLR", "DRU"), ("BER", "PAL", "SHD")]
)
@pytest.mark.parametrize("role", wp.ROLES)
@pytest.mark.parametrize("level", [50, 55])
def test_a_trio_without_dual_wield_never_gets_dw(trio, role, level):
    assert "dw" not in wp.setups_for(trio, role, real_tables(), level=level)


def test_a_trio_with_a_dual_wield_class_gets_dw():
    tables = real_tables()
    assert "dw" in wp.setups_for(("PAL", "MNK", "BER"), "melee", tables)  # the Monk
    assert "dw" in wp.setups_for(("WAR", "CLR", "SHM"), "tank", tables)  # the Warrior


@pytest.mark.parametrize("trio", [("WIZ", "MAG", "ENC"), ("SHD", "CLR", "SHM"), ("PAL", "MNK", "BER")])
def test_the_caster_role_gets_the_stick_alone(trio):
    assert wp.setups_for(trio, "caster", real_tables()) == ["stick"]


def test_wiz_mag_enc_caster_is_the_stick_and_pal_mnk_ber_melee_is_two_hander_and_dual_wield():
    assert wp.setups_for(("WIZ", "MAG", "ENC"), "caster", real_tables()) == ["stick"]
    assert wp.setups_for(("PAL", "MNK", "BER"), "melee", real_tables()) == ["2h", "dw"]


@pytest.mark.parametrize(
    ("trio", "role", "expected"),
    [
        (("PAL", "MNK", "BER"), "tank", ["1h-shield", "2h", "dw"]),
        (("PAL", "MNK", "BER"), "balanced", ["1h-shield", "2h", "dw"]),
        (("SHD", "CLR", "SHM"), "tank", ["1h-shield", "2h"]),
        (("SHD", "CLR", "SHM"), "melee", ["2h"]),
        (("SHD", "CLR", "SHM"), "balanced", ["1h-shield", "2h", "stick"]),
        (("WAR", "CLR", "SHM"), "balanced", ["1h-shield", "2h", "dw", "stick"]),
        (("BRD", "RNG", "BST"), "melee", ["2h", "dw"]),
        (("BRD", "RNG", "BST"), "balanced", ["1h-shield", "2h", "dw"]),
        # casters have one-handed and two-handed blunt skills; with no pool nothing says no shield exists for them
        (("WIZ", "MAG", "ENC"), "balanced", ["1h-shield", "2h", "stick"]),
    ],
)
def test_each_role_gets_its_setups_in_the_fixed_order(trio, role, expected):
    assert wp.setups_for(trio, role, real_tables()) == expected


def test_availability_is_read_at_the_level_asked_for_and_a_zero_cap_is_no_skill():
    tables = SimpleNamespace(
        skillcap={("PAL", "Dual Wield", 55): 100, ("PAL", "Dual Wield", 50): 0, ("PAL", "2H Blunt", 50): 10},
        rules=RULES,
    )
    trio = ("PAL", "CLR", "DRU")
    assert wp.setups_for(trio, "melee", tables, level=50) == ["2h"]
    assert wp.setups_for(trio, "melee", tables, level=55) == ["dw"]
    assert wp.setups_for(trio, "melee", tables) == ["2h"]  # the level defaults to the rules' current level (50)


def test_a_role_with_nothing_available_still_gets_the_stick():
    assert wp.setups_for(("PAL", "CLR", "DRU"), "melee", SimpleNamespace(skillcap={}, rules=RULES)) == ["stick"]


def test_unknown_roles_and_classes_are_refused():
    with pytest.raises(ValueError, match="role"):
        wp.setups_for(("PAL", "MNK", "BER"), "healer", real_tables())
    with pytest.raises(ValueError, match="class"):
        wp.setups_for(("PAL", "MNK", "XXX"), "melee", real_tables())


# ---- who can wear a shield -------------------------------------------------------------------------------------


def test_shield_availability_comes_from_the_class_lists_of_the_shields_in_the_pool():
    shield = item("shield-one", is_shield=True, classes=("PAL",), slots=("SECONDARY",))
    everyone = item("shield-two", is_shield=True, classes=("ALL",), slots=("SECONDARY",))
    sword = item("sword", weapon=weapon(10, 20), classes=("ALL",))
    assert wp.shield_available(("PAL", "MNK", "BER"), [shield]) is True
    assert wp.shield_available(("WIZ", "MAG", "ENC"), [shield]) is False
    assert wp.shield_available(("WIZ", "MAG", "ENC"), [everyone]) is True
    assert wp.shield_available(("PAL", "MNK", "BER"), [sword]) is False  # a one-hander is no shield
    assert wp.shield_available(("PAL", "MNK", "BER"), []) is False


def test_without_a_pool_a_shield_is_assumed_for_every_trio_there_is_no_list_of_classes_that_never_wear_one():
    # who can wear a shield is read from the class lists of the shields in the pool; with no pool there is nothing to
    # read, and no class is ruled out by a guess (a shield exists whose class list holds casters, and a Monk's)
    assert not hasattr(wp, "NO_SHIELD_CLASSES")
    for trio in (("MNK", "NEC", "WIZ"), ("MAG", "ENC", "NEC"), ("MNK", "NEC", "SHD"), ("PAL", "MNK", "BER")):
        assert wp.shield_available(trio) is True
        assert wp.shield_available(trio, None) is True


def test_the_pool_decides_whether_a_role_gets_one_hander_and_shield():
    trio, tables = ("PAL", "MNK", "BER"), real_tables()
    shield = item("shield-one", is_shield=True, classes=("PAL",), slots=("SECONDARY",))
    sword = item("sword", weapon=weapon(10, 20), classes=("ALL",))
    assert wp.setups_for(trio, "tank", tables, items=[shield, sword]) == ["1h-shield", "2h", "dw"]
    assert wp.setups_for(trio, "tank", tables, items=[sword]) == ["2h", "dw"]
    casters = ("WIZ", "MAG", "ENC")
    everyone = item("shield-two", is_shield=True, classes=("ALL",), slots=("SECONDARY",))
    assert wp.setups_for(casters, "balanced", tables, items=[everyone]) == ["1h-shield", "2h", "stick"]


def test_a_shield_for_casters_gives_casters_the_shield_setup_and_a_shield_for_other_classes_does_not():
    tables, casters = real_tables(), ("WIZ", "MAG", "ENC")
    for_casters = item("shield-three", is_shield=True, classes=("CLR", "DRU", "SHM", "NEC", "WIZ", "MAG", "ENC"), slots=("SECONDARY",))
    for_fighters = item("shield-four", is_shield=True, classes=("WAR", "PAL", "SHD"), slots=("SECONDARY",))
    held = item("focus", is_shield=False, classes=("ALL",), slots=("SECONDARY",))  # a held item is no shield
    assert wp.setups_for(casters, "balanced", tables, items=[for_casters]) == ["1h-shield", "2h", "stick"]
    assert wp.setups_for(casters, "balanced", tables, items=[for_fighters, held]) == ["2h", "stick"]
    assert wp.setups_for(casters, "balanced", tables, items=[]) == ["2h", "stick"]
    # a Monk is in the class list of one shield of the catalog: the pool says so, not a list of classes in the code
    for_monks = item("shield-five", is_shield=True, classes=("WAR", "MNK", "ROG"), slots=("SECONDARY",))
    assert wp.setups_for(("MNK", "NEC", "WIZ"), "balanced", tables, items=[for_monks]) == ["1h-shield", "2h", "dw", "stick"]
    assert wp.setups_for(("MNK", "NEC", "WIZ"), "balanced", tables, items=[for_fighters]) == ["2h", "dw", "stick"]


# ---- which items a setup allows in a hand ------------------------------------------------------------------------

ONE = item("one-hander", weapon=weapon(20, 30), slots=("PRIMARY", "SECONDARY"))
TWO = item("two-hander", weapon=weapon(40, 60, skill="2H Blunt", two_handed=True))
SHIELD = item("shield", is_shield=True, slots=("SECONDARY",))
HELD = item("held", slots=("SECONDARY",))


@pytest.mark.parametrize(
    ("setup", "hand", "allowed"),
    [
        ("2h", "primary", {TWO}),
        ("2h", "secondary", set()),
        ("dw", "primary", {ONE}),
        ("dw", "secondary", {ONE}),
        ("1h-shield", "primary", {ONE}),
        ("1h-shield", "secondary", {SHIELD}),
        ("stick", "primary", {ONE, TWO, SHIELD, HELD}),
        ("stick", "secondary", {ONE, SHIELD, HELD}),  # a two-hander never stands in the off hand, whatever the setup
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_each_setup_allows_these_items_in_this_hand(setup, hand, allowed):
    everything = [ONE, TWO, SHIELD, HELD]
    assert [i for i in everything if wp.allowed_in_hand(i, hand, setup)] == [i for i in everything if i in allowed]


@pytest.mark.parametrize("setup", wp.SETUPS)
def test_a_two_hander_is_never_allowed_in_the_off_hand_whatever_the_setup(setup):
    assert wp.allowed_in_hand(TWO, "secondary", setup) is False
    # the same weapon as a one-hander is only limited by the setup, and the off hand of a two-hander list changes nothing
    listed = item("listed-two-hander", weapon=weapon(40, 60, skill="2H Slashing", two_handed=True), slots=("PRIMARY", "SECONDARY"))
    assert wp.allowed_in_hand(listed, "secondary", setup) is False
    assert wp.allowed_in_hand(listed, "primary", setup) is (setup in ("2h", "stick"))


def test_an_unknown_setup_or_hand_is_refused():
    with pytest.raises(ValueError, match="setup"):
        wp.allowed_in_hand(ONE, "primary", "club")
    with pytest.raises(ValueError, match="hand"):
        wp.allowed_in_hand(ONE, "head", "dw")


# ---- the damage index ----------------------------------------------------------------------------------------------


def test_golden_one_hander_with_the_half_delay_bonus():
    w = item("sword", weapon=weapon(20, 30))  # bonus 0.5 x 30 = 15, so (20 + 15) / 30
    assert wp.damage_index_exact(w, "primary", "dw", 0, RULES) == Fraction(35, 30)
    assert wp.damage_index_exact(w, "primary", "dw", 50, RULES) == Fraction(7, 4)
    index = wp.damage_index(w, "primary", "dw", 50, RULES)
    assert isinstance(index, float) and index == pytest.approx(1.75)
    assert wp.damage_index(w, "primary", "1h-shield", 50, RULES) == index  # the same main hand in any setup


def test_a_two_hander_uses_the_listed_bonus_when_there_is_one():
    w = item("greatsword", weapon=weapon(33, 44, skill="2H Slashing", bonus=20, two_handed=True))
    assert wp.damage_index_exact(w, "primary", "2h", 0, RULES) == Fraction(53, 44)


@pytest.mark.parametrize("listed", [None, 0])
def test_without_a_listed_bonus_a_two_hander_gets_067_delay_capped_at_50_and_a_one_hander_half_the_delay(listed):
    big = item("maul", weapon=weapon(37, 70, skill="2H Blunt", bonus=listed, two_handed=True))
    assert wp.damage_index_exact(big, "primary", "2h", 0, RULES) == (37 + Fraction(67, 100) * 50) / 70
    small = item("dirk", weapon=weapon(10, 24, bonus=listed))
    assert wp.damage_index_exact(small, "primary", "dw", 0, RULES) == (10 + 12) / Fraction(24)


def test_the_off_hand_gets_the_dual_wield_factor_and_no_bonus_and_only_in_dw():
    w = item("sword", weapon=weapon(20, 30), slots=("PRIMARY", "SECONDARY"))
    assert wp.damage_index_exact(w, "secondary", "dw", 50, RULES, dw_factor=Fraction(4, 5)) == Fraction(20, 30) * Fraction(3, 2) * Fraction(4, 5)
    for setup in ("1h-shield", "2h", "stick"):
        assert wp.damage_index_exact(w, "secondary", setup, 50, RULES) == 0
    assert wp.damage_index_exact(w, "primary", "dw", 50, RULES) == Fraction(7, 4)  # the main hand has no factor


def test_the_dual_wield_factor_can_be_given_or_comes_from_a_rule_when_the_rules_have_one():
    w = item("sword", weapon=weapon(20, 30), slots=("PRIMARY", "SECONDARY"))
    third = Fraction(20, 30)
    assert wp.damage_index_exact(w, "secondary", "dw", 0, RULES, dw_factor=0.5) == third / 2
    assert wp.damage_index_exact(w, "secondary", "dw", 0, RULES, dw_factor=Fraction(1, 4)) == third / 4
    with_rule = SimpleNamespace(get=lambda rule_id, level=50: {"weapons.dual_wield_factor": 0.75}[rule_id])
    assert wp.damage_index_exact(w, "secondary", "dw", 0, with_rule) == third * Fraction(3, 4)
    with pytest.raises(ValueError, match="dual_wield_factor"):  # the real rule has a value for each kind of trio
        wp.damage_index_exact(w, "secondary", "dw", 0, RULES)
    no_rule = SimpleNamespace(get=lambda rule_id, level=50: {}[rule_id])
    assert wp.damage_index_exact(w, "secondary", "dw", 0, no_rule) == third * Fraction(4, 5)  # no such rule: the default
    assert wp.damage_index_exact(w, "secondary", "dw", 0) == third * Fraction(4, 5)  # no rules at all


@pytest.mark.parametrize(
    ("it", "hand", "setup"),
    [
        (TWO, "primary", "dw"),
        (TWO, "secondary", "dw"),
        (TWO, "primary", "1h-shield"),
        (ONE, "primary", "2h"),
        (SHIELD, "secondary", "1h-shield"),
        (HELD, "primary", "dw"),
        (ONE, "primary", "stick"),
        (TWO, "primary", "stick"),
    ],
)
def test_an_item_the_setup_does_not_allow_in_that_hand_adds_nothing(it, hand, setup):
    assert wp.damage_index_exact(it, hand, setup, 40, RULES) == 0
    assert wp.damage_index(it, hand, setup, 40, RULES) == 0.0


def test_a_weapon_without_damage_or_delay_adds_nothing():
    for broken in (weapon(0, 30), weapon(20, 0), weapon(None, 30), weapon(20, None)):
        assert wp.damage_index_exact(item("odd", weapon=broken), "primary", "dw", 0, RULES) == 0


@given(
    dmg=st.integers(1, 300),
    delay=st.integers(10, 100),
    bonus=st.one_of(st.none(), st.integers(0, 80)),
    two=st.booleans(),
    haste=st.integers(0, 85),
)
def test_the_index_scales_with_haste_exactly_and_is_never_negative(dmg, delay, bonus, two, haste):
    w = item("w", weapon=weapon(dmg, delay, bonus=bonus, two_handed=two, skill="2H Blunt" if two else "1H Blunt"))
    setup = "2h" if two else "dw"
    base = wp.damage_index_exact(w, "primary", setup, 0, RULES)
    assert base > 0
    assert wp.damage_index_exact(w, "primary", setup, haste, RULES) == base * (100 + haste) / 100
    assert wp.damage_index(w, "primary", setup, haste, RULES) == pytest.approx(float(base) * (100 + haste) / 100)


# ---- the haste the objective assumes ------------------------------------------------------------------------------


def test_the_assumed_haste_is_the_spell_haste_plus_the_best_worn_piece_up_to_the_cap():
    profile = SimpleNamespace(haste_cap=75, spell_haste=40)
    assert wp.haste_assumed(profile, [item("a", haste=20), item("b", haste=10), item("c")]) == 60
    assert wp.haste_assumed(profile, [item("a", haste=50)]) == 75
    assert wp.haste_assumed(profile, []) == 40


def test_the_assumed_haste_never_goes_over_the_cap_and_ignores_worn_haste_below_zero():
    assert wp.haste_assumed(SimpleNamespace(haste_cap=75, spell_haste=80), []) == 75
    assert wp.haste_assumed(SimpleNamespace(haste_cap=40, spell_haste=45), [item("a", haste=5)]) == 40
    assert wp.haste_assumed(SimpleNamespace(haste_cap=85, spell_haste=0), [item("a", haste=36)]) == 36
    assert wp.haste_assumed(SimpleNamespace(haste_cap=75, spell_haste=10), [item("a", haste=-5)]) == 10
    assert type(wp.haste_assumed(SimpleNamespace(haste_cap=75, spell_haste=10), [item("a", haste=7)])) is int
