"""Tests for what the kit checks read from the item table alone: the armour classes, the robes and the set stems.

The invented table of ``kits_fixture`` has two armour sets for each list of classes (five lists of three classes or more, and a list of a single class), so that the thresholds
of the module are met with ``min_items=2``.
"""

from __future__ import annotations

import pytest
from kits_fixture import CHAIN, CLOTH, NONCLOTH, PIECES, PLATE, ROBE_CLASSES, armour, base_items, item, items_document

from trioforge import rules as rules_module
from trioforge.checks import families
from trioforge.checks.families import ARMOUR_SLOTS, armour_classes, is_robe, set_stems, stem_of
from trioforge.checks.results import ItemTable
from trioforge.classes import CLASS_CODES


@pytest.fixture(scope="module")
def rules():
    return rules_module.load()


def _table(records, rules):
    return ItemTable(items_document(records), rules)


def test_the_heaviest_armour_is_what_the_class_lists_say(rules):
    found = armour_classes(_table(base_items(), rules), min_items=2)
    assert found.heavy == frozenset(PLATE)
    assert found.cloth == frozenset(CLOTH)
    assert {len(s) for s in found.sets} == {5, 8, 12, 4, 16}  # plate, chain, all but cloth, cloth, every class


def test_a_list_of_one_class_is_a_class_piece_not_a_weight_of_armour(rules):
    records = [r for r in base_items() if not r["name"].startswith(("Vlorn", "Quibbit"))]  # no plate set at all: the Monk-only sets are the only small lists
    found = armour_classes(_table(records, rules), min_items=2)
    assert frozenset({"MNK"}) not in found.sets
    assert "MNK" not in found.heavy


def test_a_set_must_have_enough_items_in_every_armour_slot(rules):
    plate_helms = {"Vlorn Helm", "Quibbit Helm", "Phantom Helm", "Zealot Helm", "Disputed Helm", "Ogrebite Helm"}
    records = [r for r in base_items() if r["name"] not in plate_helms]  # the plate list has no helm left: it is no generic set
    found = armour_classes(_table(records, rules), min_items=2)
    assert frozenset(PLATE) not in found.sets
    assert found.heavy == frozenset(CHAIN)  # the next list down is the heaviest there is


def test_a_table_with_one_armour_weight_has_no_heavy_class(rules):
    records = armour("Plainth", None, 3) + armour("Gruel", None, 2)
    found = armour_classes(_table(records, rules), min_items=2)
    assert found.heavy == frozenset() and found.cloth == frozenset()


def test_the_armour_classes_are_read_from_the_pool_alone(rules):
    """A hidden, disputed, deity-locked or hand-in item is in no solve pool: its class list says nothing of what a kit can wear."""
    records = [r for r in base_items() if not r["name"].startswith(("Vlorn", "Quibbit"))]  # no plate item in the pool but the ones below
    for name in ("Hid", "Dis", "Dei", "Han"):
        for slot, word in PIECES.items():
            level = {"Hid": "hidden", "Dis": "disputed"}.get(name, "wiki")
            records.append(item(f"{name} {word}", [slot], PLATE, {"AC": 30}, level=level, deity=["Zeta"] if name == "Dei" else None, codes=["not-for-bis"] if name == "Han" else ()))
            records.append(item(f"{name}B {word}", [slot], PLATE, {"AC": 30}, level=level, deity=["Zeta"] if name == "Dei" else None, codes=["not-for-bis"] if name == "Han" else ()))
    found = armour_classes(_table(records, rules), min_items=2)
    assert frozenset(PLATE) not in found.sets  # the plate list is only in items that no solve pool holds
    assert found.heavy == frozenset(CHAIN)


def test_the_robe_is_a_robe_by_the_caster_classes_of_the_model(rules):
    found = armour_classes(_table(base_items(), rules), min_items=2)
    assert found.casters == frozenset({"CLR", "DRU", "SHM", "NEC", "WIZ", "MAG", "ENC"})  # the classes of the caster role


def test_the_default_threshold_is_three_items_of_the_pool_a_slot(rules):
    assert families.MIN_SET_ITEMS == 3
    assert armour_classes(_table(base_items(), rules)).heavy == frozenset()  # two sets a list are not three items a slot


@pytest.mark.parametrize(
    ("classes", "robe"),
    [
        (ROBE_CLASSES, True),
        (CLOTH, True),
        (("ENC",), True),
        (("ENC", "DRU"), True),  # casters, one of them cloth
        (("ENC", "MNK"), False),  # a Monk wears it: no robe, whatever else it lists
        (("ENC", "MNK", "ROG", "DRU", "BST"), False),  # a strap of cloth, leather and chain wearers
        (("MNK",), False),  # leather alone is no robe
        (("DRU", "SHM"), False),  # no cloth class
        (PLATE, False),
        (("WAR", "ENC"), False),  # a heavy class can wear it
        (("CLR", "ENC"), False),  # a Cleric wears plate
        (NONCLOTH, False),
        (None, False),  # every class
    ],
)
def test_a_robe_is_a_piece_of_casters_that_lists_a_cloth_class_and_no_heavy_class(rules, classes, robe):
    found = armour_classes(_table(base_items(), rules), min_items=2)
    assert is_robe(None if classes is None else frozenset(classes), found) is robe


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        ("Marrow Veil Headband", "marrow veil"),
        ("Plated Boots", "plated"),
        ("Crown of the Zindrel", "of zindrel"),
        ("Ring of an Old Order", "of old order"),
        ("Cloak of Embrelle", "of embrelle"),
        ("Ring of the Zindrel (Test)", "of zindrel"),
        ("Headband", None),
        ("Hind Straps of Brixton", "of brixton"),
        ("  Spaced   Out  Name  ", "spaced out"),
        ("Of", None),
    ],
)
def test_the_stem_of_a_name(name, stem):
    assert stem_of(name) == stem


def test_a_stem_is_a_set_when_enough_items_in_enough_slots_carry_it(rules):
    table = _table(base_items(), rules)
    stems = set_stems(table, min_slots=4, min_items=3)
    keys = {r.name: r.key for r in table.records.values()}
    assert {stems[keys[f"Vlorn {word}"]] for word in ("Helm", "Boots", "Tunic")} == {"vlorn"}
    assert keys["Glimmer Idol"] not in stems and keys["Brawn Belt"] not in stems  # one word before the last: "glimmer", one item
    assert len(set(stems.values())) == 12  # the twelve armour sets of the table, one stem each


def test_the_pieces_of_a_set_need_different_slots_and_the_pool_decides(rules):
    records = [item(f"Wedge Piece {n}", ["HEAD"], None, {"AC": 1}) for n in range(5)]  # five items, one slot
    records += [item(f"Chair {word}", [slot], None, {"AC": 1}) for slot, word in (("HEAD", "Helm"), ("FEET", "Boots"), ("CHEST", "Tunic"), ("ARMS", "Sleeves"))]
    records += [item(f"Hidden {word}", [slot], None, {"AC": 1}, level="hidden") for slot, word in (("HEAD", "Helm"), ("FEET", "Boots"), ("CHEST", "Tunic"), ("ARMS", "Sleeves"))]
    records += [item(f"Zealous {word}", [slot], None, {"AC": 1}, deity=["Zeta"]) for slot, word in (("HEAD", "Helm"), ("FEET", "Boots"), ("CHEST", "Tunic"), ("ARMS", "Sleeves"))]
    records.append(item("Quad Cape", ["BACK", "SHOULDERS", "ARMS", "WAIST"], None, {"AC": 1}))  # one item in four slots is no set
    table = _table(records, rules)
    found = set(set_stems(table, min_slots=4, min_items=3).values())
    assert found == {"chair"}  # not "wedge piece" (one slot), not "hidden" (out of the pool), not "zealous" (a deity's), not "quad" (one item)
    assert set(set_stems(table, min_slots=1, min_items=3).values()) == {"chair", "wedge piece"}


def test_the_six_armour_slots_are_those_of_the_brief():
    assert ARMOUR_SLOTS == ("CHEST", "LEGS", "ARMS", "HEAD", "HANDS", "FEET")
    assert set(CLASS_CODES) >= set(PLATE) | set(CLOTH)
