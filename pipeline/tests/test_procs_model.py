"""The weapon procs of the score: the table of a trio (:mod:`trioforge.model.procs`) and what the evaluator does with it (stage 1b of the builds).

Every item, class pairing and effect here is invented. A proc is worth ``value`` (procs a minute times the damage-equivalent of one) and adds ``value / 600`` to the
weapon index of the hand that swings it, with no haste factor; the off hand takes the dual-wield factor.
"""

from fractions import Fraction

import pytest
from solver_helpers import TABLES, kit_from_groups, make_item, make_profile

from trioforge.model import formulas as fm
from trioforge.model import roles
from trioforge.model.items import SLOT_INSTANCES, WeaponVec
from trioforge.model.procs import ProcDonor, ProcEffect, ProcTable

TRIO = ("WAR", "SHM", "ENC")
DMG = 600  # a weight that makes the arithmetic round
ONE_HAND = WeaponVec("1H Slashing", 30, 30, 0, False)  # a swing of (30 + 15) / 30 = 3/2 an index point at no haste
TWO_HAND = WeaponVec("2H Slashing", 60, 40, 0, True)  # (60 + 0.6875 x 40 x 60 / 50) / 40 = 2.325 at level 50 (T9: the damage is above the level)
SWING_ONE_HAND = Fraction(3, 2)


def effect(name, value):
    return ProcEffect(f"e-{name}", name.title(), Fraction(value))


def donor(name, key, slots=("PRIMARY", "SECONDARY"), classes=TRIO, primary_only=False, lore=False):
    return ProcDonor(f"e-{name}", key, frozenset(slots), frozenset(classes), primary_only, lore)


def table(effects, donors, trio=TRIO, socket=4):
    return ProcTable(trio, socket, tuple(effects), tuple(donors))


def blade(key, tier=4, weapon=ONE_HAND, slots=("PRIMARY", "SECONDARY"), classes=TRIO, lore=False):
    return make_item(key, slots, weapon=weapon, classes=classes, tier=tier, lore=lore)


def worth(profile, kit, setup, table_, haste=0):
    return fm.evaluate(profile, kit, setup=setup, haste_assumed=haste, procs=table_)


def hands(primary=None, secondary=None):
    return kit_from_groups({"PRIMARY": [primary] if primary else [], "SECONDARY": [secondary] if secondary else []})


@pytest.fixture(scope="module")
def profile():
    return make_profile(TRIO, "HUM", {"DMG": DMG}, dw_factor=Fraction(1, 2))


# ---- the table ---------------------------------------------------------------------------------------------------------------------------------------------


def test_below_the_socket_tier_an_item_counts_its_own_best_proc_only():
    cold = table(
        [effect("frost", 300), effect("flame", 500), effect("borrowed", 900)],
        [donor("frost", "axe"), donor("flame", "axe"), donor("borrowed", "far-off")],
    )
    entries = cold.entries(blade("axe", tier=3), "PRIMARY")
    assert [(e.effect, e.value, e.donor, e.mode) for e in entries] == [("e-flame", 500, "axe", "n")]  # one proc, the best of its own; nothing is hosted below +4


def test_at_the_socket_tier_an_item_counts_the_best_proc_it_can_host_and_the_native_is_one_of_them():
    warm = table(
        [effect("frost", 300), effect("flame", 500), effect("borrowed", 900)],
        [donor("frost", "axe"), donor("flame", "axe"), donor("borrowed", "far-off")],
    )
    entries = warm.entries(blade("axe", tier=4), "PRIMARY")
    assert [(e.effect, e.donor, e.mode) for e in entries] == [("e-borrowed", "far-off", "h"), ("e-flame", "axe", "n")]  # the top two by value, hosted first


def test_a_native_proc_better_than_every_hosted_one_stays_and_a_hosted_one_better_than_the_native_replaces_it():
    pair = table([effect("own", 800), effect("lent", 200)], [donor("own", "axe"), donor("lent", "far-off")])
    assert pair.entries(blade("axe"), "PRIMARY")[0].effect == "e-own"
    pair = table([effect("own", 200), effect("lent", 800)], [donor("own", "axe"), donor("lent", "far-off")])
    best = pair.entries(blade("axe"), "PRIMARY")[0]
    assert (best.effect, best.donor, best.mode) == ("e-lent", "far-off", "h")


def test_a_third_proc_does_not_push_the_value_best_out_of_the_top_two():
    three = table(
        [effect("a", 100), effect("b", 400), effect("c", 700)], [donor("a", "d-a"), donor("b", "d-b"), donor("c", "d-c")]
    )
    assert [e.effect for e in three.entries(blade("axe"), "PRIMARY")] == ["e-c", "e-b"]


def test_a_donor_with_no_class_overlap_with_the_host_is_not_hosted():
    split = table([effect("shaman", 900)], [donor("shaman", "totem", classes=("SHM",))])
    assert split.entries(blade("axe", classes=("WAR",)), "PRIMARY") == ()  # no class of the trio can use both
    assert [e.effect for e in split.entries(blade("axe", classes=("WAR", "SHM")), "PRIMARY")] == ["e-shaman"]


def test_a_donor_needs_a_slot_in_common_with_the_host_and_a_primary_only_donor_needs_the_primary_hand():
    only = table(
        [effect("pole", 900), effect("blunt", 400)],
        [donor("pole", "polearm", slots=("PRIMARY",), primary_only=True), donor("blunt", "club", slots=("SECONDARY",))],
    )
    item = blade("axe")
    assert [e.effect for e in only.entries(item, "PRIMARY")] == ["e-pole", "e-blunt"]  # the club shares the secondary slot with the axe
    assert [e.effect for e in only.entries(item, "SECONDARY")] == ["e-blunt"]  # a primary-only donor is hosted in the primary hand alone
    plain = blade("pick", slots=("PRIMARY",))
    assert [e.effect for e in only.entries(plain, "PRIMARY")] == ["e-pole"]  # (no slot in common with the club)


def test_equal_values_record_the_donor_with_the_smallest_item_key():
    tie = table(
        [effect("x", 500), effect("y", 500)], [donor("x", "w20"), donor("x", "w10"), donor("y", "w05")]
    )
    entries = tie.entries(blade("axe"), "PRIMARY")
    assert [(e.effect, e.donor) for e in entries] == [("e-y", "w05"), ("e-x", "w10")]  # the donor of an effect is the smallest key, and equal values go to the smaller


def test_an_item_with_nothing_to_count_has_no_entries_and_the_answer_is_cached():
    empty = table([effect("x", 500)], [donor("x", "w10", classes=("SHM",))])
    item = blade("axe", classes=("WAR",))
    assert empty.entries(item, "PRIMARY") == ()
    full = table([effect("x", 500)], [donor("x", "w10")])
    assert full.entries(blade("axe"), "PRIMARY") is full.entries(blade("axe"), "PRIMARY")


# ---- the best pair of hands ---------------------------------------------------------------------------------------------------------------------------------


def test_a_lore_proc_wanted_by_both_hands_is_used_once_and_the_other_hand_takes_its_next():
    shared = table(
        [effect("rare", 900), effect("common", 300)], [donor("rare", "relic", lore=True), donor("common", "club")]
    )
    main, off = shared.best(blade("axe"), blade("sword"), Fraction(1, 2))
    assert (main.effect, off.effect) == ("e-rare", "e-common")  # the main hand's value counts in full, the off hand's by the factor
    plenty = table([effect("rare", 900), effect("common", 300)], [donor("rare", "relic"), donor("common", "club")])
    main, off = plenty.best(blade("axe"), blade("sword"), Fraction(1, 2))
    assert (main.effect, off.effect) == ("e-rare", "e-rare")  # two copies of the donor exist: both hands carry it


def test_the_other_hand_gives_way_when_that_is_worth_more():
    shared = table(
        [effect("rare", 900), effect("good", 880), effect("poor", 10)], [donor("rare", "relic", lore=True), donor("good", "gem"), donor("poor", "rag")]
    )
    # the off hand counts half: rare in the main hand and good in the off hand is 900 + 440, good in the main hand and rare in the off hand 880 + 450
    main, off = shared.best(blade("axe"), blade("sword"), Fraction(1, 2))
    assert (main.effect, off.effect) == ("e-rare", "e-good") and main.value + off.value / 2 == 900 + 440


def test_natives_below_the_socket_never_share_a_copy():
    cold = table([effect("rare", 900)], [donor("rare", "axe")])
    main, off = cold.best(blade("axe", tier=3), blade("axe", tier=3), Fraction(1, 2))
    assert (main.effect, off.effect) == ("e-rare", "e-rare")  # each copy of the item carries its own


# ---- the evaluator ------------------------------------------------------------------------------------------------------------------------------------------


def test_a_proc_adds_its_value_over_600_to_the_index_of_the_hand_that_swings_it(profile):
    t = table([effect("flame", 300)], [donor("flame", "axe")])
    plain = worth(profile, hands(blade("axe")), "1h-shield", None)
    with_proc = worth(profile, hands(blade("axe")), "1h-shield", t)
    assert plain.parts["WEAPON"] == DMG * SWING_ONE_HAND
    assert with_proc.parts["WEAPON"] == DMG * (SWING_ONE_HAND + Fraction(300, 600))
    assert with_proc.F - plain.F == DMG * Fraction(1, 2)
    assert with_proc.totals["procs"]["PRIMARY"].effect == "e-flame" and with_proc.totals["procs"]["SECONDARY"] is None
    assert "procs" not in plain.totals  # no table, no new key: every earlier result reads as it did


def test_the_proc_has_no_haste_factor_while_the_swing_keeps_its_own(profile):
    t = table([effect("flame", 300)], [donor("flame", "axe")])
    at_fifty = worth(profile, hands(blade("axe")), "1h-shield", t, haste=50)
    assert at_fifty.parts["WEAPON"] == DMG * (SWING_ONE_HAND * Fraction(3, 2) + Fraction(1, 2))
    truthful = fm.evaluate_truthful(profile, hands(blade("axe")), {"HASTE": 30}, setup="1h-shield", procs=t)
    assert truthful.parts["WEAPON"] == DMG * (SWING_ONE_HAND * Fraction(13, 10) + Fraction(1, 2))
    again = fm.evaluate(profile, hands(blade("axe")), {"HASTE": 30}, setup="1h-shield", haste_assumed=30, procs=t)
    assert truthful.F == again.F  # the truthful value is the value at the haste the kit counts, to the last bit


def test_the_off_hand_counts_a_proc_by_the_dual_wield_factor(profile):
    t = table([effect("flame", 300), effect("frost", 120)], [donor("flame", "axe"), donor("frost", "sword")])
    both = worth(profile, hands(blade("axe", tier=3), blade("sword", tier=3)), "dw", t)  # below +4: each hand its own
    swing = DMG * (SWING_ONE_HAND + Fraction(1, 2) * (Fraction(30, 30)))
    assert both.parts["WEAPON"] == swing + DMG * (Fraction(300, 600) + Fraction(120, 600) * Fraction(1, 2))
    assert both.totals["procs"]["SECONDARY"].effect == "e-frost"


def test_a_build_that_scores_no_weapon_gets_no_proc():
    quiet = make_profile(TRIO, "HUM", {"HP": 1})  # the shield caster, the caster tank and the caster have a damage weight of 0
    t = table([effect("flame", 300)], [donor("flame", "axe")])
    result = worth(quiet, hands(blade("axe")), "1h-shield", t)
    assert result.parts["WEAPON"] == 0 and result.totals["procs"]["PRIMARY"] is None


def test_a_weapon_in_an_any_place_does_not_swing_and_carries_no_proc(profile):
    t = table([effect("flame", 300)], [donor("flame", "axe")])
    kit = kit_from_groups({"ANY": [blade("axe")]})
    result = worth(profile, kit, "1h-shield", t)
    assert result.parts["WEAPON"] == 0 and result.totals["procs"]["PRIMARY"] is None


@pytest.mark.parametrize("setup", ["stick", "ranged", None])
def test_the_stick_and_the_bow_setup_score_no_proc_in_the_hands(profile, setup):
    t = table([effect("flame", 300)], [donor("flame", "axe")])
    result = worth(profile, hands(blade("axe")), setup, t)
    assert result.parts["WEAPON"] == 0 and result.totals["procs"]["PRIMARY"] is None


def test_the_bow_in_the_range_place_scores_no_proc_in_this_stage(profile):
    t = table([effect("flame", 300)], [donor("flame", "bow", slots=("RANGE",))])
    bow = make_item("bow", ("RANGE",), weapon=WeaponVec("Archery", 30, 30, None, False), classes=TRIO, tier=4)
    result = worth(profile, kit_from_groups({"RANGE": [bow]}), "ranged", t)
    assert result.parts["WEAPON"] == DMG * Fraction(1) and result.totals["procs"] == {"PRIMARY": None, "SECONDARY": None, "index": 0, "part": 0}  # the bow's own swing and nothing else


def test_a_two_hander_is_scored_in_the_two_hand_setup_only(profile):
    t = table([effect("flame", 600)], [donor("flame", "maul", slots=("PRIMARY",), primary_only=True)])
    maul = blade("maul", weapon=TWO_HAND, slots=("PRIMARY",))
    inside = worth(profile, hands(maul), "2h", t)
    assert inside.totals["procs"]["PRIMARY"].effect == "e-flame" and inside.parts["WEAPON"] > 0
    outside = worth(profile, hands(maul), "dw", t)  # a pool of dual wield cannot hold one, and a kit that does scores nothing for it
    assert outside.parts["WEAPON"] == 0 and outside.totals["procs"]["PRIMARY"] is None


def test_the_tank_factor_scales_a_proc_exactly_as_it_scales_the_swing():
    rules = TABLES.rules
    tank, melee = (roles.weights_for(("WAR", "MNK", "BER"), role, rules) for role in ("tank", "melee"))
    assert tank["DMG"] != melee["DMG"]  # two builds with two damage weights
    t = table([effect("flame", 300)], [donor("flame", "axe", classes=("WAR", "MNK", "BER"))], trio=("WAR", "MNK", "BER"))
    item = blade("axe", classes=("WAR", "MNK", "BER"))
    shares = []
    for weights in (tank, melee):
        p = make_profile(("WAR", "MNK", "BER"), "HUM", {"DMG": weights["DMG"]})
        result = worth(p, hands(item), "1h-shield", t)
        proc_part = result.totals["procs"]["part"]
        shares.append(proc_part / (result.parts["WEAPON"] - proc_part))
    assert shares[0] == shares[1] == Fraction(1, 2) / SWING_ONE_HAND  # the proc is worth the same share of the swing in both builds
