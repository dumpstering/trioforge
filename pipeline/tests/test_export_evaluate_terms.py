"""Tests for the term cases of the exact evaluator: ``trioforge.export.evaluate_terms`` and ``fixtures/evaluate-terms.json``.

The JS port of the evaluator is held to the Python one on the parity fixtures (random kits) and, term by term, on these cases:
invented profiles and kits that stand on both sides of every knee, softcap, Monk bin and cap, each with the exact breakdown that
``formulas.evaluate`` gives. The tests check that

* the committed file is what the script makes now (it is never edited by hand), and a second build is the same document;
* every case is the exact breakdown of the inputs it stores (read back from the JSON, which is what the port reads);
* the cases reach the regimes they are for: every knee (100, 200, 201, 255, 510), the softcap with and without a shield, the Monk bins
  below, at and above a bin edge, Iksar, mixed WIS/INT mana, END, and the other terms of the evaluator;
* every item in them is invented.

Every name here is invented or a public game term.
"""

import json
from fractions import Fraction
from pathlib import Path

import pytest

from trioforge.export import browser, evaluate_terms
from trioforge.export.fixture_cases import breakdown_json, buffset_from_doc, eval_totals_for
from trioforge.model import formulas as fm
from trioforge.model.items import SLOT_INSTANCES, ItemVec, WeaponVec
from trioforge.model.profile import Profile
from trioforge.model.tables import load as load_tables

TABLES = load_tables()
RULES = TABLES.rules
REGENERATE = "python -m trioforge.export.evaluate_terms --out fixtures/evaluate-terms.json"


@pytest.fixture(scope="module")
def built():
    return evaluate_terms.build()


@pytest.fixture(scope="module")
def committed():
    assert evaluate_terms.PATH.is_file(), f"the term cases are missing: run {REGENERATE}"
    return json.loads(evaluate_terms.PATH.read_text(encoding="ascii"))


# ---- helpers -----------------------------------------------------------------------------------------------------------------


def item_of(entry):
    """The ItemVec of a stored item (the fields the evaluator reads; the others are filled in)."""
    weapon = entry["weapon"]
    if weapon is not None:
        weapon = WeaponVec(weapon["skill"], weapon["dmg"], weapon["delay"], weapon["bonus"], weapon["two_handed"])
    return ItemVec(
        key=entry["key"], name=entry["key"], slots=frozenset({"ANY"}), classes=frozenset({"WAR"}), deity=None, lore=False,
        stats=dict(entry["stats"]), sv=dict(entry["sv"]), haste=entry["haste"], weight10=entry["weight10"], weapon=weapon,
        is_shield=entry["is_shield"], tier=0,
    )  # fmt: skip


def evaluated_again(doc, case):
    """The breakdown of a stored case, made again by the Python evaluator from what the case stores."""
    profile = Profile.from_dict(doc["profiles"][case["profile"]])
    kit = [None] * len(SLOT_INSTANCES)
    for index, entry in case["kit"]:
        kit[index] = item_of(entry)
    totals = None
    if case["buffs"] is not None:
        totals = eval_totals_for(buffset_from_doc(case["buffset"]), case["buffs"])
    return fm.evaluate(profile, kit, totals, setup=case["setup"], haste_assumed=case["haste"])


def tagged(doc, tag):
    return [case for case in doc["cases"] if tag in case["tags"]]


def attribute(case, stat):
    """The exact total of an attribute in the stored breakdown of a case."""
    return browser.unrat(case["breakdown"]["totals"]["attributes"][stat])


def profile_of(doc, case):
    return Profile.from_dict(doc["profiles"][case["profile"]])


def compare(row):
    """-1, 0 or 1: whether X of a stored sheet is below, at or above the softcap Y."""
    x, y = browser.unrat(row["X"]), browser.unrat(row["Y"])
    return (x > y) - (x < y)


def values(doc, tag, *path):
    """The exact numbers (as Fractions) at ``path`` of the stored breakdown of every case with the tag."""
    found = []
    for case in tagged(doc, tag):
        node = case["breakdown"]
        for step in path:
            node = node[step]
        found.append(browser.unrat(node))
    return found


# ---- the file ----------------------------------------------------------------------------------------------------------------


def test_the_committed_file_is_what_the_script_makes_now(built):
    """Fails when the rules, the client tables or the evaluator change: regenerate it with the command in REGENERATE."""
    assert evaluate_terms.PATH.read_text(encoding="ascii") == evaluate_terms.render(built), f"regenerate it: {REGENERATE}"


def test_a_second_build_is_the_same_document_and_the_same_text(built):
    again = evaluate_terms.build()
    assert again == built and evaluate_terms.render(again) == evaluate_terms.render(built)


def test_the_file_says_what_it_is_and_for_which_rules(committed):
    assert committed["kind"] == "evaluate-terms" and committed["format"] == 1
    assert committed["rules_version"] == RULES.version and committed["level"] == RULES.get("level.current")
    assert set(committed) == {"format", "kind", "rules_version", "level", "terms", "profiles", "cases"}
    assert len(committed["cases"]) >= 100 and len({case["id"] for case in committed["cases"]}) == len(committed["cases"])
    assert len({json.dumps(profile, sort_keys=True) for profile in committed["profiles"]}) == len(committed["profiles"])


def test_every_term_has_a_description_and_cases(committed):
    used = {tag for case in committed["cases"] for tag in case["tags"]}
    assert used == set(committed["terms"]) and all(text for text in committed["terms"].values())
    assert set(evaluate_terms.TERMS) == set(committed["terms"])
    assert all(len(tagged(committed, tag)) >= 2 for tag in committed["terms"])


def test_every_case_is_the_exact_breakdown_of_the_inputs_it_stores(committed):
    for case in committed["cases"]:
        assert breakdown_json(evaluated_again(committed, case)) == case["breakdown"], case["id"]


def test_every_case_has_a_kit_of_places_that_exist_and_items_that_are_invented(committed):
    for case in committed["cases"]:
        places = [index for index, _ in case["kit"]]
        assert places == sorted(set(places)) and all(0 <= index < len(SLOT_INSTANCES) for index in places), case["id"]
        for _, entry in case["kit"]:
            key = entry["key"]  # an invented key starts with "it", which no catalog key does
            assert key.startswith("it") and key.replace("-", "").isalnum(), key
    races = {Profile.from_dict(profile).race for profile in committed["profiles"]}
    assert races <= {"HUM", "IKS"}


# ---- what the cases reach ----------------------------------------------------------------------------------------------------


def test_the_attribute_cases_stand_on_both_sides_of_every_knee_with_the_attributes_alike_and_apart(committed):
    wanted = {99, 100, 101, 199, 200, 201, 202, 254, 255, 256, 509, 510, 511}
    alike = tagged(committed, "attributes-alike")
    assert {attribute(case, "WIS") for case in alike} >= wanted
    for case in alike:
        totals = {browser.unrat(text) for text in case["breakdown"]["totals"]["attributes"].values()}
        assert len(totals) == 1, case["id"]
    for stat in ("STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA"):  # in the rotated cases every attribute visits every value
        assert {attribute(case, stat) for case in tagged(committed, "attributes-rotated")} >= wanted, stat
    for case in tagged(committed, "attributes-rotated"):
        assert len({text for text in case["breakdown"]["totals"]["attributes"].values()}) >= 4, case["id"]
    for knee, around in (
        ("knee-100", {99, 100, 101}), ("knee-200", {199, 200, 201}), ("knee-201", {200, 201, 202}),
        ("knee-255", {254, 255, 256}), ("knee-510", {509, 510, 511}),
    ):  # fmt: skip
        assert {attribute(case, "WIS") for case in tagged(committed, knee)} >= around, knee


def test_the_end_cases_stand_beside_both_knees_of_the_average_and_past_the_cap_of_a_stat(committed):
    averages = set(values(committed, "end", "totals", "end_average"))
    assert averages >= {Fraction(n) for n in (99, 100, 101, 200, 201, 202)}
    assert averages >= {Fraction(401, 4), Fraction(803, 4), Fraction(805, 4), Fraction(405, 2)}  # between whole numbers
    assert any(a < 0 for a in averages) or any(a < 100 for a in averages)
    capped = [
        case for case in tagged(committed, "end")
        if any(attribute(case, stat) > 510 for stat in ("STR", "STA", "AGI", "DEX"))
    ]  # fmt: skip
    assert capped and all(browser.unrat(case["breakdown"]["totals"]["end_average"]) <= 510 for case in capped)
    assert any(browser.unrat(case["breakdown"]["totals"]["end_average"]) == 510 for case in tagged(committed, "end"))


def test_the_softcap_cases_have_x_below_at_and_above_y_with_a_shield_and_without(committed):
    def rows(tag):
        return [case["breakdown"]["totals"]["sheet"] for case in tagged(committed, tag)]

    plain = rows("softcap")
    assert plain and all(row["shield_ac"] == "0/1" for row in plain)
    assert {compare(row) for row in plain} == {-1, 0, 1}  # below, at and above the softcap
    shielded = rows("softcap-shield")
    assert shielded and all(browser.unrat(row["shield_ac"]) > 0 for row in shielded)
    assert {compare(row) for row in shielded} == {-1, 0, 1}
    # a shield in an Any place, and a plain item in the off hand, are worn armor class and not the shield
    odd = tagged(committed, "shield-not-offhand")
    assert odd and all(case["breakdown"]["totals"]["sheet"]["shield_ac"] == "0/1" for case in odd)
    assert {case["kit"][-1][0] for case in odd} >= {SLOT_INSTANCES.index("ANY"), SLOT_INSTANCES.index("SECONDARY")}
    # the rate past the cap: none, all of it, and the class's own
    rates = {profile_of(committed, case).softcap[1] for case in tagged(committed, "softcap")}
    assert {0, 1} <= rates and len(rates) >= 3


def test_the_monk_cases_stand_below_at_and_above_every_bin_edge_in_both_placements_and_past_the_table(committed):
    bins = browser.monk_bins(committed["level"], RULES)
    table = [browser.unrat(text) for text in bins["bonus"]]
    soft, hard = (browser.unrat(bins["curve"][key]) for key in ("softcap_stones", "hardcap_stones"))
    cases = tagged(committed, "monk")
    weights = {browser.unrat(case["breakdown"]["totals"]["weight10"]) for case in cases}
    for stone in (soft, soft + 1, hard - 2, hard - 1, hard, hard + 1, hard + 2, len(table) - 1):
        assert {10 * stone - 1, 10 * stone, 10 * stone + 1} <= weights, stone  # a bin edge is a multiple of ten tenths
    assert max(weights) // 10 > len(table) - 1  # a weight past the table
    bonuses = {browser.unrat(case["breakdown"]["totals"]["sheet"]["monk_bonus"]) for case in cases}
    assert max(bonuses) > 0 > min(bonuses) and 0 in bonuses
    placements = {profile_of(committed, case).placement["monk"] for case in cases}
    assert placements == {"top", "inside"}
    for case in cases:  # the stored bonus is the bin of the whole stones of the stored weight (the last bin past the table)
        profile = profile_of(committed, case)
        sheet = case["breakdown"]["totals"]["sheet"]
        stones = browser.unrat(case["breakdown"]["totals"]["weight10"]) // 10
        if "full_until_stones" not in profile.monk:
            assert browser.unrat(sheet["monk_bonus"]) == table[min(stones, len(table) - 1)], case["id"]
    alternative = [c for c in cases if "full_until_stones" in profile_of(committed, c).monk]
    assert alternative, "the alternative reading of the curve (the full bonus up to N whole stones)"
    (alt,) = bins["alternatives"]
    alt_table = [browser.unrat(text) for text in alt["bonus"]]
    for case in alternative:
        stones = browser.unrat(case["breakdown"]["totals"]["weight10"]) // 10
        assert browser.unrat(case["breakdown"]["totals"]["sheet"]["monk_bonus"]) == alt_table[min(stones, len(alt_table) - 1)]
    assert all(profile_of(committed, case).monk is not None for case in cases)


def test_the_iksar_cases_have_the_racial_armor_class_on_top_and_inside_with_and_without_a_monk(committed):
    cases = tagged(committed, "iksar")
    profiles = [profile_of(committed, case) for case in cases]
    bonus = RULES.get("race.iksar_ac_bonus")
    assert {p.placement["iksar"] for p in profiles} == {"top", "inside"} and {p.iksar_ac for p in profiles} == {bonus}
    assert {p.monk is None for p in profiles} == {True, False}
    assert {p.race for p in profiles} == {"IKS"}
    assert all(case["breakdown"]["totals"]["sheet"]["iksar"] == f"{RULES.get('race.iksar_ac_bonus')}/1" for case in cases)
    assert {case["breakdown"]["parts"]["IKSAR"] == "0/1" for case in cases} == {True, False}  # a part when on top, none inside


def test_the_mixed_mana_cases_change_which_pools_count_with_ties_in_trio_order(committed):
    cases = tagged(committed, "mixed-mana")
    counted = {tuple(case["breakdown"]["totals"]["counted"]["MANA"]) for case in cases}
    assert ("CLR", "SHD") in counted  # a tie between the WIS pool and the INT pools: the trio's order decides
    assert ("SHD", "ENC") in counted  # INT above WIS: the two INT pools
    assert any(c[0] == "CLR" and c[1] in ("SHD", "ENC") for c in counted)  # WIS above INT: the WIS pool and one INT pool
    assert any(attribute(case, "WIS") > attribute(case, "INT") for case in cases)
    assert any(attribute(case, "WIS") < attribute(case, "INT") for case in cases)


def test_the_pool_cases_have_pools_that_cross_and_tie(committed):
    cases = tagged(committed, "pool-order")
    assert len({tuple(case["breakdown"]["totals"]["counted"]["HP"]) for case in cases}) >= 3
    assert len({tuple(case["breakdown"]["totals"]["counted"]["END"]) for case in cases}) >= 2
    ties = 0
    for case in cases:
        pools = profile_of(committed, case).pools["HP"]
        eff = fm.effective_sta(attribute(case, "STA"))
        scores = [fm.HP_POOL_CONSTANT + p.base + p.fac * eff for p in pools]
        ties += len(set(scores)) < len(scores)
    assert ties >= 1


def test_the_weapon_cases_have_every_setup_and_hand_a_listed_bonus_none_and_zero_and_a_fractional_haste(committed):
    cases = tagged(committed, "weapons")
    assert {case["setup"] for case in cases} == {None, "1h-shield", "2h", "dw", "stick", "ranged"}
    assert {case["haste"] for case in cases} >= {0, 25, 12.5}
    parts = [browser.unrat(case["breakdown"]["parts"]["WEAPON"]) for case in cases]
    assert any(p == 0 for p in parts) and any(p > 0 for p in parts)
    weapons = [entry["weapon"] for case in cases for _, entry in case["kit"] if entry["weapon"] is not None]
    assert {w["bonus"] for w in weapons} >= {None, 0} and any(w["bonus"] for w in weapons)
    assert {w["two_handed"] for w in weapons} == {True, False}
    main = [entry["weapon"] for case in cases for index, entry in case["kit"] if index == SLOT_INSTANCES.index("PRIMARY")]
    assert any(w and w["bonus"] == 0 and not w["two_handed"] for w in main)  # a main hand with a bonus listed as 0 ...
    assert any(w and w["bonus"] == 0 and w["two_handed"] for w in main)  # ... of either kind
    hands = {index for case in cases for index, entry in case["kit"] if entry["weapon"] is not None}
    assert hands >= {SLOT_INSTANCES.index("PRIMARY"), SLOT_INSTANCES.index("SECONDARY"), SLOT_INSTANCES.index("RANGE")}


def test_the_buff_cases_choose_among_the_optional_buffs_with_duplicates_always_on_ids_and_the_best_haste(committed):
    cases = tagged(committed, "buffs")
    chosen = [case["buffs"] for case in cases]
    assert None in chosen and [] in chosen and any(c and len(c) > len(set(c)) for c in chosen)
    always = {buff_id for case in cases if case["buffset"] for buff_id in case["buffset"]["set"]["always_on"]}
    assert any(set(c or ()) & always for c in chosen)
    hastes = {case["breakdown"]["totals"]["haste"]["spell"] for case in cases}
    assert len(hastes) >= 3
    (buffset,) = {json.dumps(case["buffset"], sort_keys=True) for case in cases if case["buffset"]}
    table = json.loads(buffset)["table"]
    always_on = json.loads(buffset)["set"]["always_on"]
    assert sum("HASTE" in table[str(buff_id)]["vec"] for buff_id in always_on) >= 2  # two always-on hastes: the best counts


def test_the_other_terms_have_cases_on_both_sides_of_their_caps(committed):
    haste = tagged(committed, "haste")
    rows = [case["breakdown"]["totals"]["haste"] for case in haste]
    trimmed = {row["worn_counted"] != row["worn_best"] for row in rows}
    assert trimmed == {True, False}  # the cap leaves room for all of the worn haste, and for part of it
    for key, family in (("HPREG", "HP"), ("MANAREG", "MANA"), ("ENDREG", "END")):  # gear regen below, at and above its cap
        cases = tagged(committed, "regen")
        cap = profile_of(committed, cases[0]).caps["regen"][family]
        gear = {browser.unrat(case["breakdown"]["totals"]["regen"][key]["gear"]) for case in cases}
        assert any(g < cap for g in gear) and cap in gear and any(g > cap for g in gear), key
        assert all(browser.unrat(case["breakdown"]["totals"]["regen"][key]["buff"]) > 0 for case in cases)  # outside the cap
    cases = tagged(committed, "resists")  # gear and buff together below, at and above the cap
    cap = profile_of(committed, cases[0]).caps["resist"]
    sums = {
        browser.unrat(row["gear"]) + browser.unrat(row["buff"])
        for case in cases for row in case["breakdown"]["totals"]["resists"].values()
    }  # fmt: skip
    assert any(s < cap for s in sums) and cap in sums and any(s > cap for s in sums)
    assert any(case["breakdown"]["totals"]["pools"]["MANA"] == "0/1" for case in tagged(committed, "mana-none"))
    assert tagged(committed, "empty") and tagged(committed, "decimals")
    limits = tagged(committed, "limits")
    sums = [browser.unrat(case["breakdown"]["totals"]["weight10"]) for case in limits]
    assert max(sums) == 22 * 2**40 and min(sums) == -22 * 2**40  # 22 items at the limit of what an item holds
    assert any(abs(browser.unrat(case["breakdown"]["parts"]["HP"])) > 2**90 for case in limits)  # far past a double
    weights = [profile_of(committed, case).weights for case in limits]
    assert any("1.5e-08" in json.dumps(committed["profiles"][case["profile"]]) for case in limits) and weights
    inexact = [p for p in committed["profiles"] if any(isinstance(v, float) and v != int(v) for v in p["naked"].values())]
    assert inexact  # a decimal where the profile holds whole numbers
    text = json.dumps(committed["profiles"])
    assert '"1/3"' in text  # a pool number that a float cannot carry is written as p/q


# ---- the command -------------------------------------------------------------------------------------------------------------


def test_the_command_writes_the_file_and_checks_it(tmp_path, capsys):
    target = tmp_path / "terms.json"
    assert evaluate_terms.main(["--out", str(target)]) == 0
    assert target.read_text(encoding="ascii") == evaluate_terms.PATH.read_text(encoding="ascii")
    assert evaluate_terms.main(["--out", str(target), "--check"]) == 0
    target.write_text(target.read_text(encoding="ascii").replace('"level": 50', '"level": 51'), encoding="ascii")
    assert evaluate_terms.main(["--out", str(target), "--check"]) == 1
    assert "differs" in capsys.readouterr().err
    assert evaluate_terms.main(["--out", str(tmp_path / "missing" / "terms.json"), "--check"]) == 1
