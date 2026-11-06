"""The "why" of the kit rows of a trio page (p7kit): what each stat of an item is worth in the default kit, and the stats of a row.

``trioforge.precompute.kitwhy`` values the default kit with ``evaluate_truthful`` (the kit at the haste it counts, as the solver does) and
again with one stat of one item taken away: the difference is what that stat is worth there, so a stat past its cap shows 0. The site
(``trioforge.site.view``) words it, and words the stats of a row from ``at_tier``, the numbers the solver used. These tests hold the loss to
the evaluator's own difference, to the last bit, on hand-built kits.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction as F

import pytest

from solver_helpers import make_buff, make_buffset, make_item
from trioforge.model.formulas import EvalProfile, PoolSpec, evaluate_truthful
from trioforge.model.items import SLOT_INSTANCES, WeaponVec
from trioforge.precompute import kitwhy

NAKED = {k: 100 for k in "STR STA AGI DEX WIS INT CHA".split()}
POOLS = {
    "HP": (PoolSpec("WAR", 1500, 5.0), PoolSpec("CLR", 1320, 4.4), PoolSpec("ENC", 1200, 4.0)),
    "MANA": (PoolSpec("CLR", 900, 4.5, "WIS"), PoolSpec("ENC", 900, 4.5, "INT")),
    "END": (PoolSpec("WAR", 900, 4.5), PoolSpec("CLR", 456, 3.25), PoolSpec("ENC", 260, 1.25)),
}
WEIGHTS = {"HP": 1, "AC": 2, "ATK": 1, "HASTE": 30, "DMG": 40, "SV": 3, "HPREG": 5, "DEX": 1}


def profile(**changes):
    base = dict(level=50, naked=NAKED, weights=WEIGHTS, pools=POOLS, haste_cap=75, softcap=(400, F(1, 4)), caps={"regen": {"HP": 30, "MANA": 15, "END": 15}, "resist": 200})
    base.update(changes)
    return EvalProfile(**base)


def kit_of(**places):
    """A kit of 22 places: ``places`` maps a place name (HEAD, PRIMARY, EAR_2 for the second ear) to an item."""
    kit = [None] * len(SLOT_INSTANCES)
    seen = {}
    for index, name in enumerate(SLOT_INSTANCES):
        seen[name] = seen.get(name, 0) + 1
        key = name if seen[name] == 1 else f"{name}_{seen[name]}"
        if key in places:
            kit[index] = places[key]
    return kit


def independent_loss(prof, kit, index, change, totals=None, setup="dw"):
    """The kit's value less the value with the item of ``index`` changed, by the evaluator alone (written out again here)."""
    base = evaluate_truthful(prof, kit, totals, setup=setup).F
    trial = list(kit)
    trial[index] = dataclasses.replace(kit[index], **change)
    return base - evaluate_truthful(prof, trial, totals, setup=setup).F


def terms(place):
    return {term[0]: term for term in place["loss"]}


# ---- the loss of a stat ---------------------------------------------------------------------------------------------------------


def test_the_loss_of_a_stat_below_its_cap_is_the_evaluators_difference_exactly():
    prof = profile()
    helm = make_item("helm", {"HEAD"}, stats={"AC": 20, "HP": 50, "ATK": 12})
    kit = kit_of(HEAD=helm)
    rows = kitwhy.why_places(prof, kit, None, "stick")
    head = rows[SLOT_INSTANCES.index("HEAD")]
    assert head["key"] == "helm"
    for stat in ("AC", "HP", "ATK"):
        without = {k: v for k, v in helm.stats.items() if k != stat}
        want = independent_loss(prof, kit, 0, {"stats": without}, setup="stick")
        assert want > 0
        assert terms(head)[stat][1] == float(want)  # exactly, not nearly
    assert [term[0] for term in head["loss"]] == sorted(terms(head), key=lambda stat: -terms(head)[stat][1])  # the largest loss first


def test_a_resist_past_the_cap_loses_nothing_and_says_why():
    prof = profile()
    cloak = make_item("cloak", {"BACK"}, sv={"FIRE": 40})
    ring_a = make_item("ring_a", {"FINGER"}, sv={"FIRE": 150})
    ring_b = make_item("ring_b", {"FINGER"}, sv={"FIRE": 150})
    kit = kit_of(BACK=cloak, FINGER=ring_a, FINGER_2=ring_b)  # 340 fire against a cap of 200
    rows = kitwhy.why_places(prof, kit, None, "stick")
    back = terms(rows[SLOT_INSTANCES.index("BACK")])["FIRE"]
    assert tuple(back) == ("FIRE", 0.0, "resist-cap")  # (the cloak's 40 are all past the cap)
    assert back[1] == float(independent_loss(prof, kit, SLOT_INSTANCES.index("BACK"), {"sv": {}}, None, "stick")) == 0.0
    ring = terms(rows[SLOT_INSTANCES.index("FINGER")])["FIRE"]  # without a ring the count is 190, 10 short of the cap
    assert ring[1] == float(independent_loss(prof, kit, SLOT_INSTANCES.index("FINGER"), {"sv": {}}, None, "stick")) > 0
    assert ring[2] is None  # (no reason is given for a stat that is worth something)


def test_a_resist_below_the_cap_loses_what_it_takes_off_the_count():
    prof = profile()
    cloak = make_item("cloak", {"BACK"}, sv={"FIRE": 90})
    ring = make_item("ring", {"FINGER"}, sv={"FIRE": 150})
    kit = kit_of(BACK=cloak, FINGER=ring)  # 240 of a cap of 200: without the cloak the count is 150 (50 short), without the ring 90 (110 short)
    rows = kitwhy.why_places(prof, kit, None, "stick")
    cloak_term = terms(rows[SLOT_INSTANCES.index("BACK")])["FIRE"]
    ring_term = terms(rows[SLOT_INSTANCES.index("FINGER")])["FIRE"]
    assert cloak_term[1] == float(independent_loss(prof, kit, SLOT_INSTANCES.index("BACK"), {"sv": {}}, None, "stick"))
    assert ring_term[1] == float(independent_loss(prof, kit, SLOT_INSTANCES.index("FINGER"), {"sv": {}}, None, "stick"))
    assert 0 < cloak_term[1] < ring_term[1]


def test_worn_haste_past_the_cap_loses_nothing_and_one_item_covered_by_a_better_one_says_so():
    prof = profile(haste_cap=75)
    buffset = make_buffset(always=[make_buff(900, haste=50)])
    from solver_helpers import eval_totals

    totals = eval_totals(buffset, ())
    belt = make_item("belt", {"WAIST"}, haste=30)
    boots = make_item("boots", {"FEET"}, haste=20)
    kit = kit_of(WAIST=belt, FEET=boots)  # spell haste 50 of a cap of 75: the belt's 30 count 25, and the boots (20) add nothing beyond the belt
    rows = kitwhy.why_places(prof, kit, totals, "stick")
    boots_term = terms(rows[SLOT_INSTANCES.index("FEET")])["HASTE"]
    assert boots_term[1] == 0.0 and boots_term[2] == "haste-covered"
    belt_term = terms(rows[SLOT_INSTANCES.index("WAIST")])["HASTE"]
    assert belt_term[1] == float(independent_loss(prof, kit, SLOT_INSTANCES.index("WAIST"), {"haste": 0}, totals, "stick")) > 0
    at_cap = profile(haste_cap=50)
    rows = kitwhy.why_places(at_cap, kit, totals, "stick")
    assert tuple(terms(rows[SLOT_INSTANCES.index("WAIST")])["HASTE"][1:]) == (0.0, "haste-cap")


def test_a_haste_stat_is_valued_with_the_weapon_it_speeds_up():
    """Taking the haste off the belt also slows the weapon: the loss is the truthful difference, which is more than the haste term alone."""
    prof = profile()
    belt = make_item("belt", {"WAIST"}, haste=25)
    sword = make_item("sword", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 20, 30, None, False))
    kit = kit_of(WAIST=belt, PRIMARY=sword)
    rows = kitwhy.why_places(prof, kit, None, "dw")
    loss = terms(rows[SLOT_INSTANCES.index("WAIST")])["HASTE"][1]
    assert loss == float(independent_loss(prof, kit, SLOT_INSTANCES.index("WAIST"), {"haste": 0}, None, "dw"))
    assert loss > float(WEIGHTS["HASTE"] * 25)  # the haste term alone is 750; the sword's damage rose with it
    sword_term = terms(rows[SLOT_INSTANCES.index("PRIMARY")])["DAMAGE"]
    assert sword_term[1] == float(independent_loss(prof, kit, SLOT_INSTANCES.index("PRIMARY"), {"weapon": None}, None, "dw")) > 0


def test_a_negative_stat_has_a_negative_loss_and_sorts_last():
    prof = profile()
    shield = make_item("heavy", {"CHEST"}, stats={"AC": 30, "AGI": -12, "HP": 20})
    kit = kit_of(CHEST=shield)
    rows = kitwhy.why_places(prof, kit, None, "stick")
    chest = rows[SLOT_INSTANCES.index("CHEST")]
    agi = terms(chest)["AGI"]
    assert agi[1] == float(independent_loss(prof, kit, SLOT_INSTANCES.index("CHEST"), {"stats": {"AC": 30, "HP": 20}}, None, "stick"))
    assert agi[1] < 0 and chest["loss"][-1][0] == "AGI"


def test_an_empty_place_has_no_row_and_a_stat_the_model_does_not_score_is_left_out():
    prof = profile()
    bad = make_item("odd", {"HEAD"}, stats={"HP": 10}, sv={"CORRUPTION": 40})
    rows = kitwhy.why_places(prof, kit_of(HEAD=bad), None, "stick")
    assert rows[1] is None and len(rows) == len(SLOT_INSTANCES)
    assert [term[0] for term in rows[0]["loss"]] == ["HP"]


def test_the_same_item_in_two_places_is_judged_place_by_place():
    prof = profile()
    ring = make_item("ring", {"FINGER"}, sv={"FIRE": 120})
    kit = kit_of(FINGER=ring, FINGER_2=ring)  # 240 of a cap of 200: each is worth 40 less than it carries
    rows = kitwhy.why_places(prof, kit, None, "stick")
    a, b = (terms(rows[i])["FIRE"][1] for i in (SLOT_INSTANCES.index("FINGER"), SLOT_INSTANCES.index("FINGER") + 1))
    assert a == b == float(independent_loss(prof, kit, SLOT_INSTANCES.index("FINGER"), {"sv": {}}, None, "stick")) > 0
