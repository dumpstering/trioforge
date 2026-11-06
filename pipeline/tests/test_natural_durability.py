"""Natural Durability (AA 107, rank 4 = +12 percent of the HP that comes from STA), p7nek part 2.

The rule ``hp.natural_durability_pct`` says what a rank adds (2, 5, 10 and 12 percent, cumulative), the profile assumes the top
rank for every class the way it assumes Combat Stability 3 of 3, and the percent is applied to the STA part of each HP pool, the
``hp_fac x STA'`` of ``5 + base_hp + hp_fac x STA'``, and to nothing else: not the constant 5, not the class base, not the flat
HP of items and buffs. The tests hold: the rule and its sources, the known value (the maintainer's Iksar and Barbarian check:
245 HP from STA, 274 with the AA), the flat HP that is not scaled, the profile and its pools, the exact evaluator, the game
window's floors, and the file the JS port is held to (``fixtures/evaluate-terms.json``, term ``natural-durability``).
"""

from __future__ import annotations

import dataclasses
import json
from fractions import Fraction as F

import pytest

from trioforge.export import evaluate_terms
from trioforge.model import formulas as fm
from trioforge.model.items import SLOT_INSTANCES
from trioforge.model.profile import AA_CHOICES, make_profile
from trioforge.model.tables import load

TABLES = load()
RULES = TABLES.rules
TRIO = ("WAR", "MNK", "ROG")
ID = "hp.natural_durability_pct"


def profile(aa=None, trio=TRIO, race="HUM"):
    return make_profile(race, trio, 50, "balanced", None, aa, TABLES)


def kit_of(**stats):
    kit = [None] * len(SLOT_INSTANCES)
    kit[SLOT_INSTANCES.index("CHEST")] = evaluate_terms._item("itnd", stats=stats)
    return kit


# ---- the rule --------------------------------------------------------------------------------------------------------


def test_the_rule_has_the_four_ranks_a_seal_and_both_public_sources():
    assert RULES.get(ID, 50) == {"1": 2, "2": 5, "3": 10, "4": 12}
    entry = next(rule for rule in json.loads((evaluate_terms.REPO / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"] if rule["id"] == ID)
    assert entry["seal"] == "player" and entry["status"] == "active" and entry["unit"] == "percent (cumulative)"
    refs = [source["ref"] for source in entry["source"]]
    assert "dbstr_us.txt" in refs  # the shipped client text file (the schema lists the files that may be cited)
    assert any("151303" in ref and "eqlbuilds.com" in ref for ref in refs)  # the wiki's AA data, as eqlbuilds.com extracted it
    assert {source["kind"] for source in entry["source"]} == {"client-file", "public-text"}
    assert "AA 107, type 4" in entry["notes"] and "(derived from your stamina) by #1%" in entry["notes"]
    assert "costs 2, 4, 6 and 2" in entry["notes"]


# ---- the known value: the maintainer's Iksar and Barbarian check ------------------------------------------------------


def window(attrs, nd_pct=0, item=None, buff=None, trio=TRIO):
    full = {"STR": 0, "STA": 0, "AGI": 0, "DEX": 0, "WIS": 0, "INT": 0, **attrs}
    return fm.stat_window(trio, 50, full, item or {}, buff or {}, TABLES, nd_pct=nd_pct)


def test_245_hp_from_sta_is_274_with_the_aa_rounded_down():
    # A Warrior pool: hp_fac 5 and STA' 49 give 5 x 49 = 245 HP from STA. 245 x 1.12 = 274.4, and the window floors each product, so 274.
    # (The 245 and the 274 are the maintainer's check on an Iksar and a Barbarian; the rounding is the existing HP code's: floor.)
    plain = window({"STA": 49})
    with_aa = window({"STA": 49}, nd_pct=12)
    assert plain["hp_pool_values"]["WAR"] == 5 + 1500 + 245
    assert with_aa["hp_pool_values"]["WAR"] == 5 + 1500 + 274
    assert with_aa["HP"] - plain["HP"] == sum(with_aa["hp_pool_values"][c] - plain["hp_pool_values"][c] for c in with_aa["hp_pools"])


def test_each_rank_is_its_own_percent_of_the_sta_part():
    for rank, pct in ((1, 2), (2, 5), (3, 10), (4, 12)):
        got = window({"STA": 49}, nd_pct=pct)["hp_pool_values"]["WAR"]
        assert got == 5 + 1500 + (245 * (100 + pct)) // 100, rank


def test_the_sta_part_is_floored_before_the_aa_is_applied():
    # MNK: hp_fac 4.25, STA' 49 -> floor(208.25) = 208 HP from STA; 208 x 1.12 = 232.96 -> 232
    got = window({"STA": 49}, nd_pct=12)["hp_pool_values"]["MNK"]
    assert got == 5 + 1275 + 232


# ---- flat HP is not scaled ----------------------------------------------------------------------------------------------


def test_item_and_buff_hp_are_not_scaled_in_the_window():
    base = window({"STA": 95}, nd_pct=12)
    more = window({"STA": 95}, nd_pct=12, item={"HP": 100}, buff={"HP": 7})
    assert more["HP"] - base["HP"] == 107  # exactly the points, not 107 x 1.12


def test_the_constant_and_the_class_base_are_not_scaled_in_the_window():
    zero_sta = window({"STA": 0}, nd_pct=12)
    assert zero_sta["hp_pool_values"]["WAR"] == 5 + 1500  # no STA, so nothing for the AA to add to


def test_exact_hp_adds_only_the_sta_part_and_leaves_flat_hp_alone():
    for item_hp in (0, 100):
        plain = fm.hp_total(TRIO, 50, 258, item_hp, 7, TABLES)
        with_aa = fm.hp_total(TRIO, 50, 258, item_hp, 7, TABLES, nd_pct=12)
        counted = fm.counted_pools(TRIO, 50, {"STR": 0, "STA": 258, "AGI": 0, "DEX": 0, "WIS": 0, "INT": 0}, TABLES, nd_pct=12)["HP"]
        facs = {spec.cls: spec.fac for spec in fm.pools_for(TRIO, 50, TABLES)["HP"]}
        assert with_aa - plain == sum(facs[c] * fm.effective_sta(258) * F(12, 100) for c in counted)  # the same whatever the flat HP is


# ---- the profile -----------------------------------------------------------------------------------------------------------


def test_the_default_profile_has_the_top_rank_and_its_percent():
    p = profile()
    assert AA_CHOICES == ("combat_stability", "natural_durability", "physical_enhancement")
    assert p.aa["natural_durability"] == 4 and p.nd_pct == 12
    assert p.aa["combat_stability"] == 3  # (the other AAs are as they were)


def test_the_hp_pools_of_a_profile_carry_the_percent_on_their_factor_only():
    p = profile()
    table = fm.pools_for(TRIO, 50, TABLES)
    for mine, theirs in zip(p.pools["HP"], table["HP"]):
        assert (mine.cls, mine.base) == (theirs.cls, theirs.base)
        assert mine.fac == theirs.fac * F(112, 100)
    assert p.pools["MANA"] == table["MANA"] and p.pools["END"] == table["END"]


def test_rank_zero_is_the_client_pools_and_no_percent():
    p = profile({"natural_durability": 0})
    assert p.nd_pct == 0 and p.aa["natural_durability"] == 0
    assert p.pools["HP"] == fm.pools_for(TRIO, 50, TABLES)["HP"]


@pytest.mark.parametrize("rank, pct", [(1, 2), (2, 5), (3, 10), (4, 12)])
def test_a_lower_rank_is_its_own_percent(rank, pct):
    p = profile({"natural_durability": rank})
    assert p.nd_pct == pct
    assert p.pools["HP"][0].fac == fm.pools_for(TRIO, 50, TABLES)["HP"][0].fac * F(100 + pct, 100)


@pytest.mark.parametrize("bad", [5, -1, True, 2.0, "4"])
def test_a_rank_past_the_top_or_not_a_whole_number_is_refused(bad):
    with pytest.raises(ValueError, match="natural_durability"):
        profile({"natural_durability": bad})


def test_the_aa_choices_and_the_percent_are_in_the_json_and_read_back():
    p = profile()
    data = p.to_dict()
    assert data["aa"] == {"combat_stability": 3, "natural_durability": 4, "physical_enhancement": True} and data["nd_pct"] == 12
    assert type(p).from_dict(data) == p
    assert type(p).from_json(p.to_json()) == p


def test_hp_in_the_exact_evaluator_is_the_scaled_pools_plus_flat_hp_unscaled():
    p = profile()
    kit = kit_of(STA=100, HP=100)
    result = fm.evaluate(p, kit, {})
    sta_total = p.naked["STA"] + 100
    eff = fm.effective_sta(sta_total)
    table = {spec.cls: spec for spec in fm.pools_for(TRIO, 50, TABLES)["HP"]}
    pools = sorted((5 + spec.base + spec.fac * eff * F(112, 100) for spec in table.values()), reverse=True)[:2]
    assert result.totals["pools"]["HP"] == pools[0] + pools[1] + 100
    flat_only = fm.evaluate(profile({"natural_durability": 0}), kit_of(STA=100, HP=100), {})
    assert result.totals["pools"]["HP"] - flat_only.totals["pools"]["HP"] == sum(table[c].fac * eff * F(12, 100) for c in result.totals["counted"]["HP"])


def test_the_solver_values_hp_with_the_aa_exactly_as_the_evaluator_does():
    # the builder reads the profile's pools, so its HP term is the evaluator's: one tiny solve, its objective against the exact value of its kit
    from solver_helpers import eval_totals, kit_from_groups, make_item  # noqa: PLC0415
    from trioforge.solver._highs import solve_milp  # noqa: PLC0415
    from trioforge.solver.model import BuildOptions, build_milp  # noqa: PLC0415

    p = profile()
    prof = dataclasses.replace(p.eval_profile, weights={"HP": 1})
    items = [make_item("hp-a", {"CHEST"}, stats={"STA": 60, "HP": 40}), make_item("hp-b", {"CHEST"}, stats={"STA": 80})]
    options = BuildOptions(any_rule="explicit", haste_assumed=0)
    milp = build_milp(prof, items, "stick", None, options)
    res = solve_milp(milp)
    assert res.status == "optimal"
    kit = kit_from_groups(milp.decode(res.x).groups)
    exact = fm.evaluate(prof, kit, None, setup="stick", haste_assumed=milp.haste_assumed).F
    assert abs(milp.const + res.objective - float(exact)) <= 1e-9 * max(1.0, abs(float(exact)))
    without = dataclasses.replace(profile({"natural_durability": 0}).eval_profile, weights={"HP": 1})
    assert fm.evaluate(prof, kit, None, setup="stick", haste_assumed=0).F > fm.evaluate(without, kit, None, setup="stick", haste_assumed=0).F


# ---- the file the JS port is held to ----------------------------------------------------------------------------------------


def test_the_evaluate_terms_file_has_a_natural_durability_term_with_cases_at_every_rank():
    assert "natural-durability" in evaluate_terms.TERMS
    doc = json.loads(evaluate_terms.PATH.read_text(encoding="utf-8"))
    cases = [case for case in doc["cases"] if "natural-durability" in case["tags"]]
    assert len(cases) >= 6
    percents = {doc["profiles"][case["profile"]]["nd_pct"] for case in cases}
    assert percents == {0, 2, 5, 10, 12}
    assert any(case["kit"] and any(item["stats"].get("HP") for _, item in case["kit"]) for case in cases)  # flat HP among them
