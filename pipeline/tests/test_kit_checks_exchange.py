"""Tests for K10, the exchange rates of a kit: what one more point of each stat is worth to the objective of the kit, by the project's own evaluator.

The rate of a term is ``evaluate_truthful(kit with one more point of it on a worn item) - evaluate_truthful(kit)`` under the profile, the buffs and the weapon setup of the
kit. These tests work the same difference out for themselves from the model (``kits_fixture.evaluator_parts``), so what is under test is the wiring (which item, which tier, which
setup, which weights) and the refusals: a kit whose shard value is not the evaluator's value cannot be explained by the evaluator, and nothing is approximated then.
"""

from __future__ import annotations

import dataclasses

import pytest
from kits_fixture import base_items, evaluator_parts, item, make_results, row

from trioforge import rules as rules_module
from trioforge.checks.exchange import TERMS, ExchangeRates
from trioforge.checks.kits import Context
from trioforge.checks.results import PLACE_NAMES, Results, ResultsError
from trioforge.model import formulas as fm

TRIO = "pal-mnk-enc"
KIT = {"WAIST": "Brawn Belt", "HANDS": "Bruiser Mitts", "FACE": "Glimmer Idol", "EAR1": "Moonstud", "CHEST": "Vlorn Tunic", "FINGER1": "Swiftling Band", "PRIMARY": "Sorrel Staff"}


@pytest.fixture(scope="module")
def rules():
    return rules_module.load()


@pytest.fixture
def make(tmp_path, rules):
    """``make(rows, records=None)`` writes the results of PAL/MNK/ENC (human) and returns the results, their context and the item records."""
    counter = iter(range(1000))

    def build(rows, records=None):
        records = base_items() if records is None else records
        results = Results(make_results(tmp_path / f"results-{next(counter)}", records, {TRIO: rows}), rules=rules)
        return results, Context(results, min_set_items=2), records

    return build


def worked_out(records, role, tier, setup, kit):
    """The rate of every term for one more point on the first worn item, by the evaluator, worked out here."""
    compiled, vecs, totals = evaluator_parts(records, TRIO, "HUM", role, tier, kit)
    base = fm.evaluate_truthful(compiled, vecs, totals, setup=setup).F
    first = next(n for n, vec in enumerate(vecs) if vec is not None)
    best_haste = max((n for n, vec in enumerate(vecs) if vec is not None), key=lambda n: (vecs[n].haste, -n))
    found = {}
    for term in TERMS:
        trial = list(vecs)
        if term == "HASTE":
            trial[best_haste] = dataclasses.replace(vecs[best_haste], haste=vecs[best_haste].haste + 1)
        elif term in fm.SCHOOLS:
            vec = vecs[first]
            trial[first] = dataclasses.replace(vec, sv={**vec.sv, term: vec.sv.get(term, 0) + 1})
        else:
            vec = vecs[first]
            trial[first] = dataclasses.replace(vec, stats={**vec.stats, term: vec.stats.get(term, 0) + 1})
        found[term] = float(fm.evaluate_truthful(compiled, trial, totals, setup=setup).F - base)
    return found


def test_the_terms_are_those_the_design_review_asked_for():
    assert TERMS == ("STA", "STR", "AGI", "DEX", "WIS", "INT", "CHA", "AC", "HP", "MANA", "FIRE", "COLD", "MAGIC", "POISON", "DISEASE", "HASTE", "ATK")


@pytest.mark.parametrize(("role", "tier", "setup"), [("tank", 4, "2h"), ("melee", 0, "dw"), ("shield", 10, "stick")])
def test_a_rate_is_the_evaluators_change_for_one_more_point_on_a_worn_item(make, role, tier, setup):
    results, context, records = make([row(role, tier, KIT, setup=setup, value=None)])
    (kit,) = results.kits(TRIO)
    rates = ExchangeRates(context).rates(kit)
    expected = worked_out(records, role, tier, setup, KIT)
    assert list(rates["rates"]) == list(TERMS)
    assert rates["rates"] == pytest.approx(expected, abs=1e-9)
    assert rates["rates"]["STA"] > 0 and rates["value"] == pytest.approx(kit.value, abs=0.006)


def test_the_weights_of_the_role_are_those_of_the_evaluator(make):
    """A Shield caster values mana far more than a Tank does and attack far less... the point is only that the builds differ, as their weights do."""
    results, context, records = make([row("tank", 4, KIT, value=None), row("shield", 4, KIT, setup="stick", value=None)])
    kits = {kit.role: kit for kit in results.kits(TRIO)}
    tank, shield = (ExchangeRates(context).rates(kits[role])["rates"] for role in ("tank", "shield"))
    assert shield["MANA"] > tank["MANA"] and tank["ATK"] > shield["ATK"]


def test_which_worn_item_gets_the_point_does_not_change_a_plain_stat(make):
    results, context, records = make([row("tank", 4, KIT, value=None)])
    (kit,) = results.kits(TRIO)
    compiled, vecs, totals = evaluator_parts(records, TRIO, "HUM", "tank", 4, KIT)
    base = fm.evaluate_truthful(compiled, vecs, totals, setup="2h").F
    deltas = set()
    for n, vec in enumerate(vecs):
        if vec is not None:
            trial = list(vecs)
            trial[n] = dataclasses.replace(vec, stats={**vec.stats, "STA": vec.stats.get("STA", 0) + 1})
            deltas.add(float(fm.evaluate_truthful(compiled, trial, totals, setup="2h").F - base))
    assert len(deltas) == 1 and ExchangeRates(context).rates(kit)["rates"]["STA"] == pytest.approx(deltas.pop())


def test_a_resist_over_its_cap_is_worth_nothing_and_another_school_is_not(make):
    cap = {"Fireproof Test Ring": item("Fireproof Test Ring", ["FINGER"], None, None, sv={"FIRE": 1200})}  # (T4: a resist counts up to 1000)
    records = [*base_items(), *cap.values()]
    results, context, _ = make([row("tank", 4, {**KIT, "FINGER2": "Fireproof Test Ring"}, value=None)], records)
    (kit,) = results.kits(TRIO)
    rates = ExchangeRates(context).rates(kit)["rates"]
    assert rates["FIRE"] == 0 and rates["COLD"] > 0


def test_one_more_point_of_haste_goes_to_the_best_hasted_piece(make):
    results, context, records = make([row("melee", 4, KIT, setup="dw", value=None)])
    (kit,) = results.kits(TRIO)
    rates = ExchangeRates(context).rates(kit)["rates"]
    assert rates["HASTE"] > 0 and rates["HASTE"] == pytest.approx(worked_out(records, "melee", 4, "dw", KIT)["HASTE"], abs=1e-9)


def test_the_rates_are_also_given_in_units_of_a_point_of_stamina(make):
    results, context, _ = make([row("tank", 4, KIT, value=None)])
    (kit,) = results.kits(TRIO)
    rates = ExchangeRates(context).rates(kit)
    assert rates["vs_sta"]["STA"] == 1.0
    assert rates["vs_sta"]["STR"] == pytest.approx(rates["rates"]["STR"] / rates["rates"]["STA"])
    assert list(rates["vs_sta"]) == list(TERMS)


def test_a_kit_whose_shard_value_is_not_the_evaluators_is_refused_and_not_approximated(make):
    results, context, _ = make([row("tank", 4, KIT, value=1000.0)])
    (kit,) = results.kits(TRIO)
    with pytest.raises(ResultsError, match=r"evaluator.*1000"):
        ExchangeRates(context).rates(kit)


def test_a_kit_that_wears_nothing_has_no_item_to_add_a_point_to(make):
    results, context, _ = make([row("tank", 4, {}, value=None)])
    (kit,) = results.kits(TRIO)
    with pytest.raises(ResultsError, match="wears nothing"):
        ExchangeRates(context).rates(kit)


def test_the_buffs_of_the_shard_are_the_buffs_of_the_evaluation(make, tmp_path):
    """The shard names the optional buffs the solver chose (an index into ``buff_sets``); an id that the buff set of the trio does not have is an error that names it."""
    results, context, _ = make([row("tank", 4, KIT, value=None)])
    (kit,) = results.kits(TRIO)
    odd = dataclasses.replace(kit, buff_ids=(999999,))
    with pytest.raises(ResultsError, match="999999"):
        ExchangeRates(context).rates(odd)


def test_the_place_of_the_point_is_the_first_worn_place(make):
    """The point goes to the item of the lowest place in the kit's order; the rates of an item that has no such stat are the rates of a stat that it gains."""
    results, context, records = make([row("tank", 4, {"NECK": "Moonstud", "WAIST": "Brawn Belt"}, value=None)])
    (kit,) = results.kits(TRIO)
    assert next(place for place, _ in kit.worn()) == "NECK" and PLACE_NAMES.index("NECK") < PLACE_NAMES.index("WAIST")
    assert ExchangeRates(context).rates(kit)["rates"] == pytest.approx(worked_out(records, "tank", 4, "2h", {"NECK": "Moonstud", "WAIST": "Brawn Belt"}), abs=1e-9)


def test_a_kit_that_counts_a_weapon_proc_is_valued_with_it_and_a_stat_point_does_not_change_the_proc(make):
    results, context, records = make([row("melee", 4, KIT, setup="2h", value=None)])
    (kit,) = results.kits(TRIO)
    plain = ExchangeRates(context).rates(kit)
    compiled, _, _ = evaluator_parts(records, TRIO, "HUM", "melee", 4, KIT)
    part = float(compiled.weights["DMG"]) * 300 / 600  # a proc worth 300 adds 300 / 600 to the index of the two-hander, which swings
    counted = ("P", "Moon Brand", "w1", "n", 300.0)  # (the record of a shard: hand, effect, donor, mode, value)
    shown = dataclasses.replace(kit, procs=(counted,), value=round(kit.value + part, 2))
    rates = ExchangeRates(context).rates(shown)
    assert rates["rates"] == pytest.approx(plain["rates"], abs=1e-9)
    assert rates["value"] == pytest.approx(plain["value"] + part, abs=1e-9)
    with pytest.raises(ResultsError, match="K10"):
        ExchangeRates(context).rates(dataclasses.replace(kit, procs=(counted,)))  # the shard's value does not have the proc in it
