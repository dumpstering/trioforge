"""The Bow setup, the third round: what a bow is scored by.

A bow is not a melee main hand. The damage bonus that a main hand adds (the bonus its page lists, else half its delay: the pattern that the melee weapons follow) is a
main-hand rule, and nothing in the shipped client data or in a rule with a public or measured source says that archery gets it (no bow in the catalog lists a bonus at all). So a
bow in the range place of the Bow setup is scored on its own damage per delay, at the haste the kit counts, times ``weapons.ranged_factor``: ``damage / delay x (1 + haste / 100)
x factor``. The listed bonus of a bow, if a page ever lists one, is not counted either, and arrow damage never is. The note of the rule says what is and is not counted.

Every item here is invented; the classes, the skill name and the setup names are public game terms.
"""

from __future__ import annotations

import json
from fractions import Fraction as F
from pathlib import Path

import pytest
from solver_helpers import make_item
from test_ranged import RAW, RULES, bow, kit_of, profile

from trioforge.model import formulas as fm
from trioforge.model import weapons
from trioforge.model.formulas import evaluate
from trioforge.model.items import WeaponVec
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.solve import solve

REPO = Path(__file__).resolve().parents[2]


def sword(key="it-sword", dmg=45, delay=60, bonus=None):
    return make_item(key, {"PRIMARY"}, weapon=WeaponVec("1H Slashing", dmg, delay, bonus, False))


# ---- the measure ----------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("haste", [0, 25, 100])
def test_a_bow_is_scored_on_its_own_damage_per_delay_without_the_main_hand_bonus(haste):
    arrows = bow("it-bow", 45, 60)
    got = weapons.damage_index_exact(arrows, "range", "ranged", haste)
    assert got == F(45, 60) * (1 + F(haste, 100))  # not (45 + 25) / 60: no damage bonus
    # the same numbers in a main hand score the bonus, which is what the bow does not get (T9: the client's bonus at level 50, 0.5 x 50 x 0.8 x min(60, 50) / 40 = 25)
    main = weapons.damage_index_exact(sword(), "primary", "dw", haste)
    assert main == F(45 + 25, 60) * (1 + F(haste, 100)) and main > got


def test_a_bonus_that_a_bow_lists_is_not_counted_either():
    listed = bow("it-listed", 45, 60, bonus=25)
    plain = bow("it-plain", 45, 60)
    assert weapons.damage_index_exact(listed, "range", "ranged", 10) == weapons.damage_index_exact(plain, "range", "ranged", 10) == F(45, 60) * F(11, 10)
    assert weapons.damage_index_exact(sword(bonus=25), "primary", "dw", 10) == F(45 + 25, 60) * F(11, 10)  # (a main hand's listed bonus counts, as it always did)


def test_the_bow_factor_multiplies_the_bows_own_damage_per_delay():
    arrows = bow("it-bow", 33, 40)
    assert weapons.damage_index_exact(arrows, "range", "ranged", 0, ranged_factor=F(3, 4)) == F(33, 40) * F(3, 4)
    assert weapons.damage_index_exact(arrows, "range", "ranged", 20, ranged_factor=2) == F(33, 40) * F(6, 5) * 2
    assert weapons.damage_index_exact(arrows, "range", "ranged", 0, RULES) == F(33, 40)  # the rule's 1


def test_the_two_definitions_of_the_measure_agree_and_the_float_is_the_exact_value():
    for dmg, delay, bonus in ((45, 60, None), (20, 45, None), (63, 60, 12), (14, 55, 0)):
        arrows = bow("it-bow", dmg, delay, bonus=bonus)
        for haste in (0, 30, 75):
            exact = weapons.damage_index_exact(arrows, "range", "ranged", haste, ranged_factor=F(3, 2))
            assert fm.weapon_index(arrows.weapon, "RANGE", "ranged", haste, 1, F(3, 2)) == exact == F(dmg, delay) * F(100 + haste, 100) * F(3, 2)
            assert weapons.damage_index(arrows, "range", "ranged", haste, ranged_factor=F(3, 2)) == float(exact)


def test_the_evaluator_scores_the_bow_on_its_own_damage_per_delay():
    arrows = bow("it-bow", 45, 60)
    kit = kit_of(range=arrows)
    got = evaluate(profile(weights={"HP": 1, "DMG": 600}), kit, setup="ranged", haste_assumed=20).parts["WEAPON"]
    assert got == 600 * F(45, 60) * F(6, 5)


def test_the_builder_pays_the_bow_its_own_damage_per_delay_and_the_solve_is_the_evaluators():
    a, b = bow("it-a", 45, 60), bow("it-b", 30, 40)
    for haste in (0, 25):
        milp = build_milp(profile(weights={"HP": 1, "DMG": 600}), [a, b], "ranged", None, BuildOptions(any_rule="explicit", haste_assumed=haste))
        solution = solve(milp)
        worn = [item for item, place in zip(solution.kit, range(22)) if item is not None]
        assert len(worn) == 1 and worn[0].key in ("it-a", "it-b")  # (0.75 a delay unit each: a tie)
        assert solution.breakdown.parts["WEAPON"] == 600 * F(45, 60) * (1 + F(haste, 100))
        assert solution.breakdown.F == solution.model_F or abs(float(solution.breakdown.F) - solution.model_F) < 1e-6


def test_the_bows_are_ranked_by_their_damage_per_delay():
    pool = [bow("it-slow", 90, 120), bow("it-quick", 40, 40), bow("it-mid", 50, 60)]
    ranked = sorted(pool, key=lambda item: weapons.damage_index_exact(item, "range", "ranged", 0), reverse=True)
    assert [item.key for item in ranked] == ["it-quick", "it-mid", "it-slow"]
    assert [weapons.damage_index_exact(item, "range", "ranged", 0) for item in ranked] == [F(1), F(5, 6), F(3, 4)]


# ---- the note of the rule ---------------------------------------------------------------------------------------------------------------


def test_the_note_of_the_bow_factor_says_in_plain_words_what_is_and_is_not_counted():
    rule = next(rule for rule in RAW["rules"] if rule["id"] == "weapons.ranged_factor")
    notes = rule["notes"].lower()
    assert "judgment" in notes
    for word in ("damage", "delay", "haste", "arrow"):
        assert word in notes, word
    assert "bonus of a main hand is not counted" in notes and "arrow damage is not counted" in notes  # what is not counted, said in so many words
    assert "damage bonus over" not in notes  # (the first round's sentence, which said the bonus was counted)
    assert RULES.seal("weapons.ranged_factor") == "model" and RULES.get("weapons.ranged_factor") == 1.0
    assert RULES.sources("weapons.ranged_factor") == [{"kind": "public-text", "ref": "TrioForge judgment"}]


def test_no_bow_of_the_shipped_catalog_lists_a_damage_bonus():
    catalog = json.loads((REPO / "derived" / "catalog.json").read_text(encoding="utf-8"))
    bows = [i for i in catalog["items"] if ((i.get("weapon") or {}).get("skill") or "").casefold() == "archery" and "RANGE" in i["slots"]]
    assert len(bows) > 30 and all(not i["weapon"].get("bonus") for i in bows)  # (the data says nothing of a bow's bonus: so none is counted)
