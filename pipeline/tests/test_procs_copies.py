"""One physical copy supplies one hand (fix round 2, B1): two hands count the same proc only when two distinct physical copies can supply them.

The tables are made by ``score.proc_table`` from invented effect records, with the Lore flags of the items (never a hand-set count of copies). A native proc uses its own
item (the copy that is worn); a hosted proc needs a donor copy that this hand's item can host and that the other hand does not use; a Lore item is one copy and any other item two.
This holds whatever the tiers of the two hands.
"""

from fractions import Fraction

import pytest
from solver_helpers import make_item
from test_procs_value import J, damage, sitem, world

from trioforge.effects import score
from trioforge.model.items import WeaponVec

TRIO = ("WAR", "SHM", "ENC")
BOTH = ("PRIMARY", "SECONDARY")
FACTOR = Fraction(1, 2)
BLADE = WeaponVec("1H Slashing", 20, 30, None, False)


def table_of(donors, lore):
    """The table of the invented effect "Ember Brand" carried by ``donors`` ((key, slots, classes)); ``lore`` are the keys of the Lore items."""
    items = [sitem(key, list(slots), "proc", "Ember Brand", classes=classes) for key, slots, classes in donors]
    effects, ctx, book = world(items, [damage(1, "Ember Brand", 300)])
    return score.proc_table(effects, ctx, book, J, TRIO, lore=lore)


def hand(key, tier=4, classes=TRIO, slots=BOTH):
    return make_item(key, slots, weapon=BLADE, classes=classes, tier=tier)


def counted(entries):
    return [None if entry is None else entry.effect for entry in entries]


def test_s1_two_weapons_of_one_class_cannot_both_take_the_proc_when_only_one_copy_reaches_that_class():
    table = table_of([("X", BOTH, ("WAR",)), ("W", BOTH, ("SHM",))], lore={"X"})  # X is Lore and for the warrior; W is plain and for the shaman
    main, off = table.best(hand("Y1", classes=("WAR",)), hand("Y2", classes=("WAR",)), FACTOR)
    assert sorted(entry is not None for entry in (main, off)) == [False, True]  # one hand counts it, and it is the main hand (worth more there)
    assert main is not None and main.donor == "X"


def test_s1_the_same_two_weapons_both_take_a_proc_that_a_plain_donor_can_give_twice():
    table = table_of([("X", BOTH, ("WAR",)), ("W", BOTH, ("SHM",))], lore=set())  # no Lore item: each donor can be had twice
    main, off = table.best(hand("Y1", classes=("WAR",)), hand("Y2", classes=("WAR",)), FACTOR)
    assert main is not None and off is not None and main.donor == off.donor == "X"


def test_s1b_a_native_proc_keeps_its_own_item_and_the_other_hand_cannot_have_the_donor_the_first_is_using():
    # Lore X (a one-hander, both hands) and plain W (the primary hand only) carry it: the main hand wears X, which counts it natively
    table = table_of([("X", BOTH, TRIO), ("W", ("PRIMARY",), TRIO)], lore={"X"})
    main, off = table.best(hand("X"), hand("Y"), FACTOR)
    assert main is not None and (main.donor, main.mode) == ("X", "n")
    assert off is None  # W cannot be hosted in the off hand, and X is the copy the main hand uses


def test_s2_a_lore_item_below_the_socket_tier_is_not_also_the_donor_of_the_other_hand():
    table = table_of([("X", BOTH, TRIO)], lore={"X"})
    main, off = table.best(hand("X", tier=3), hand("Y", tier=4), FACTOR)
    assert main is not None and (main.donor, main.mode) == ("X", "n")
    assert off is None
    main, off = table.best(hand("Y", tier=4), hand("X", tier=3), FACTOR)  # and the other way round: the off hand wears the Lore item
    assert counted((main, off)).count(None) == 1  # one hand counts it, never both
    # (the Lore rule: the copy that is worn in the off hand is no donor for the main hand, so the off hand counts its own proc, by the factor; it was the main hand's before the rule)
    assert main is None and off is not None and (off.donor, off.mode) == ("X", "n")


def test_s5_two_lore_carriers_supply_two_hands_and_the_record_names_the_copy_that_really_supplies_it():
    table = table_of([("X1", BOTH, TRIO), ("X2", BOTH, TRIO)], lore={"X1", "X2"})
    main, off = table.best(hand("X1"), hand("Y"), FACTOR)
    assert main is not None and (main.donor, main.mode) == ("X1", "n")
    assert off is not None and (off.donor, off.mode) == ("X2", "h")  # X1 is the copy the main hand wears and uses


def test_a_plain_item_worn_in_both_hands_carries_its_proc_in_both():
    table = table_of([("X", BOTH, TRIO)], lore=set())
    main, off = table.best(hand("X"), hand("X"), FACTOR)
    assert counted((main, off)) == [table.effects[0].id] * 2 and main.mode == off.mode == "n"


def test_the_donor_a_hand_records_is_one_the_other_hand_is_not_using_in_every_case():
    for lore in (set(), {"X1"}, {"X1", "X2"}):
        table = table_of([("X1", BOTH, TRIO), ("X2", BOTH, TRIO)], lore=lore)
        main, off = table.best(hand("Y1"), hand("Y2"), FACTOR)
        assert main is not None and off is not None
        assert main.donor != off.donor or lore == set()  # two Lore copies are two items; a plain one can be had twice, so the same key may supply both
        assert {main.donor, off.donor} <= {"X1", "X2"}


@pytest.mark.parametrize("tier", [3, 4])
def test_the_rule_holds_whatever_the_tier_of_the_hand_that_wears_the_lore_item(tier):
    table = table_of([("X", BOTH, TRIO)], lore={"X"})
    main, off = table.best(hand("X", tier=tier), hand("Y", tier=4), FACTOR)
    assert main is not None and off is None


def test_one_copy_supplies_one_hand_whichever_of_its_procs_that_hand_takes():
    # Lore X carries two procs; the main hand wears X and counts one of them natively, so the off hand cannot be given the other from the same copy
    items = [sitem("X", list(BOTH), "proc", "Ember Brand"), sitem("X", list(BOTH), "proc", "Gale Brand")]
    merged = {**items[0], "effects": [*items[0]["effects"], *items[1]["effects"]]}
    effects, ctx, book = world([merged], [damage(1, "Ember Brand", 300), damage(2, "Gale Brand", 200)])
    table = score.proc_table(effects, ctx, book, J, TRIO, lore={"X"})
    main, off = table.best(hand("X"), hand("Y"), FACTOR)
    assert main is not None and main.donor == "X" and off is None
