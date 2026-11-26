"""What a weapon proc is worth (:mod:`trioforge.effects.score`): ``value = procs a minute x damage-equivalent of one``, from invented spells and items.

The numbers of the rules are those of ``rules/rules.json`` (the rate, ``(200 / 170 + 1/2) x (1 + rate / 100)``, that is 57/34 for an effect with no Rate line; the landing, 17/20; the cut of
a proc the trio casts itself, 3/20; the share of a Dismiss or Banish, 7/20); the expected values are written out here from them, in fractions.
"""

import dataclasses
from fractions import Fraction

import pytest

from trioforge.effects import donors as dn
from trioforge.effects import judgment, layer, score
from trioforge.effects import spells as sp

J = judgment.default()
PPM = Fraction(57, 34)  # (200 / 170 + 1 / 2): procs a minute at the reference DEX with no Rate line
LANDING = Fraction(17, 20)
TRIO = ("WAR", "SHM", "ENC")


def srow(sid, name, effects, ben=0, tgt=5, dur=(0, 0), levels=None):
    return {"id": sid, "name": name, "cast_ms": 0, "mana": 0, "dur": list(dur), "ben": ben, "res": 0, "tgt": tgt, "sk": 0, "lv": levels or {}, "fx": effects}


def sitem(key, slots, kind, name, raw=None, classes=("ALL",), lore=False):
    return {
        "key": key, "name": key, "slots": slots, "classes": list(classes), "tier_rule": "drop", "weapon": None, "evidence": {"level": "wiki"},
        "effects": [{"kind": kind, "name": name, "raw": raw or f"Effect: {name} (Combat)"}],
        "sources": {"drops": [{"zone": "Lower Guk", "npcs": []}], "sold_by": [], "quests": [], "crafted": []},
    }  # fmt: skip


def damage(sid, name, amount, **kw):
    return srow(sid, name, [[1, 0, -amount, 0, 100, 0]], **kw)


def world(items, rows, j=J):
    book = sp.SpellBook(rows, 50)
    pool = [sitem(*item) if isinstance(item, tuple) else item for item in items]
    effects, _ = dn.build_effects(pool, book, j)
    return effects, layer.build_context(effects, book, j), book


def value_of(items, rows, name=None, classes=TRIO, j=J):
    effects, ctx, book = world(items, rows, j)
    found = [e for e in effects if name is None or e["name"] == name]
    assert len(found) == 1, found
    return score.effect_value(found[0], ctx, book, j, classes)


def test_the_rate_is_the_rule_at_the_reference_dex_and_the_rate_line_is_applied_once():
    assert score.proc_per_minute(J, None) == PPM
    assert score.proc_per_minute(J, 50) == PPM * Fraction(3, 2)
    assert score.proc_per_minute(J, -75) == PPM / 4


def test_a_damage_proc_is_the_rate_times_its_damage_times_the_landing():
    value = value_of([("w1", ["PRIMARY"], "proc", "Blazing Brand")], [damage(1, "Blazing Brand", 200)])
    assert value == PPM * 200 * LANDING == 285


def test_a_lifetap_is_valued_as_a_damage_proc():
    spell = srow(1, "Leech Brand", [[1, 0, -200, 0, 100, 0]], tgt=13)
    assert value_of([("w1", ["PRIMARY"], "proc", "Leech Brand")], [spell]) == PPM * 200 * LANDING


def test_a_rate_line_multiplies_the_rate_once_and_the_larger_value_wins_over_the_larger_damage():
    plain = ("w1", ["PRIMARY"], "proc", "Plain Brand")
    quick = ("w2", ["PRIMARY"], "proc", "Quick Brand", "Effect: Quick Brand (Combat, Rate +50%)")
    rows = [damage(1, "Plain Brand", 200), damage(2, "Quick Brand", 150)]
    effects, ctx, book = world([plain, quick], rows)
    values = score.effect_values(effects, ctx, book, J, TRIO)
    by_name = {e["name"]: values[e["id"]] for e in effects}
    assert by_name["Plain Brand"] == PPM * 200 * LANDING
    assert by_name["Quick Brand"] == PPM * Fraction(3, 2) * 150 * LANDING  # the 50 percent once, in the rate: 150 x 1.5, not 150 x 1.5 x 1.5
    assert by_name["Quick Brand"] > by_name["Plain Brand"] and 150 < 200  # (the smaller spell is the larger proc)
    table = score.proc_table(effects, ctx, book, J, TRIO)
    assert max(table.effects, key=lambda e: e.value).name == "Quick Brand"


def test_damage_that_works_on_some_targets_only_counts_the_share_of_the_rule():
    spell = damage(1, "Banish Brand", 200, tgt=10)
    assert value_of([("w1", ["PRIMARY"], "proc", "Banish Brand")], [spell]) == PPM * 200 * LANDING * Fraction(35, 100)


def test_a_damage_over_time_that_would_outrun_its_own_duration_is_held_to_one_copy_up():
    # 10 a tick for 60 ticks (a formula-4 duration with its cap): 600 in all over 6 minutes, so one copy up is worth 100 a minute at most, and the cap carries the share that lands
    spell = srow(1, "Slow Rot", [[1, 0, -10, 0, 100, 0]], dur=(4, 60))
    assert value_of([("w1", ["PRIMARY"], "proc", "Slow Rot")], [spell]) == Fraction(600, 6) * LANDING
    banish = srow(1, "Slow Banish", [[1, 0, -10, 0, 100, 0]], dur=(4, 60), tgt=10)  # a dot of a restricted target: the cap carries that share too
    assert value_of([("w1", ["PRIMARY"], "proc", "Slow Banish")], [banish]) == Fraction(600, 6) * LANDING * Fraction(35, 100)
    # 20 a tick for 5 ticks: 100 in all over half a minute, a cap of 200 a minute that the rate (1.425 a minute of 100) does not reach
    spell = srow(1, "Quick Rot", [[1, 0, -20, 0, 100, 0]], dur=(4, 5))
    assert value_of([("w1", ["PRIMARY"], "proc", "Quick Rot")], [spell]) == PPM * 100 * LANDING == Fraction(57, 34) * 85


# ---- F1: a mixed proc is two parts: the direct hit at the rate, the lasting part under the cap of one copy up --------------------------------------------------------------


def test_a_direct_hit_with_a_lasting_part_is_valued_as_two_parts_and_the_cap_holds_the_lasting_part_alone():
    # 500 at once and 50 a tick for 10 ticks (a minute): the hit comes with every proc, the poison is one copy up, so it is worth at most its own 500 a minute; both carry the landing
    spell = srow(1, "Venom Brand", [[1, 79, -500, 0, 100, 0], [2, 0, -50, 0, 100, 0]], dur=(4, 10))
    value = value_of([("w1", ["PRIMARY"], "proc", "Venom Brand")], [spell])
    hit = PPM * 500 * LANDING  # 1425/2
    lasting = min(PPM * 500 * LANDING, 500 * LANDING * 60 / (10 * 6))  # 3.4 procs... no: 1.68 a minute of 500 is 712.5, the cap is 500 x 17/20 = 425
    assert (hit, lasting) == (Fraction(1425, 2), Fraction(425))
    assert value == hit + lasting == Fraction(2275, 2)  # 1137.5
    assert value > 850  # the whole under the cap (1000 x 17/20 x ... = 850) is what a single magnitude gave: the direct hit was capped too


def test_the_lasting_part_of_a_mixed_proc_under_its_cap_is_the_rate_times_it():
    # 100 at once and 20 a tick for 5 ticks (half a minute): the cap is 100 x 17/20 x 2 = 170 a minute, which 1.68 procs of 100 a minute (142.5) do not reach
    spell = srow(1, "Sting Brand", [[1, 79, -100, 0, 100, 0], [2, 0, -20, 0, 100, 0]], dur=(4, 5))
    assert value_of([("w1", ["PRIMARY"], "proc", "Sting Brand")], [spell]) == PPM * 100 * LANDING * 2


def test_a_restricted_target_carries_its_share_in_both_parts_of_a_mixed_proc():
    spell = srow(1, "Banish Venom", [[1, 79, -500, 0, 100, 0], [2, 0, -50, 0, 100, 0]], dur=(4, 10), tgt=10)
    value = value_of([("w1", ["PRIMARY"], "proc", "Banish Venom")], [spell])
    assert value == Fraction(2275, 2) * Fraction(35, 100)


def test_a_lifetap_with_a_lasting_part_has_that_part_under_the_cap_too():
    # (no lifetap of the client has one today: an invented spell) 100 at once and 30 a tick for 20 ticks (two minutes): the cap of the lasting 600 is 600 x 17/20 / 2 = 255 a minute
    spell = srow(1, "Leech Venom", [[1, 79, -100, 0, 100, 0], [2, 0, -30, 0, 100, 0]], dur=(4, 20), tgt=13)
    value = value_of([("w1", ["PRIMARY"], "proc", "Leech Venom")], [spell])
    assert value == PPM * 100 * LANDING + Fraction(600, 2) * LANDING == Fraction(285, 2) + Fraction(255)


def test_a_permanent_spell_with_a_one_time_part_keeps_the_parts_apart_and_has_no_cap():
    spell = srow(1, "Aura Brand", [[1, 79, -10, 0, 100, 0], [2, 0, -6, 0, 100, 0]], dur=(50, 0))
    effects, ctx, book = world([("w1", ["PRIMARY"], "proc", "Aura Brand")], [spell])
    (effect,) = effects
    assert (effect["category"], effect["magnitude"], effect["unit"], effect["once"], effect["lasting"]) == ("dot", 6, "hp_per_tick", 10, 6)  # (not 16 of hp_per_tick)
    # (G7) the one-time part comes with every proc, at the rate; the permanent part is a number for each tick, and one copy is up for ever (the first proc starts it): ten ticks a minute of 6, of which
    # 17/20 land, whatever the rate (before it was valued as damage a proc, at the rate)
    assert score.effect_value(effect, ctx, book, J, TRIO) == PPM * 10 * LANDING + 6 * 10 * LANDING


def test_the_permanent_part_of_a_spell_is_up_for_ever_so_it_does_not_follow_the_rate_and_takes_the_share_of_a_restricted_target():
    from trioforge.effects import value as value_module

    view = {"category": "dot", "once": 0, "lasting": 6, "magnitude": 6, "unit": "hp_per_tick", "duration_ticks": 0, "target": 5}
    assert value_module.damage_value(view, PPM, J) == 60 * LANDING  # 6 a tick, ten ticks a minute, 17/20 landing: 51
    assert value_module.damage_value(view, 3 * PPM, J) == 60 * LANDING  # (a Rate line does not make it tick more often)
    assert value_module.damage_value({**view, "target": 10}, PPM, J) == 60 * LANDING * Fraction(7, 20)  # (a Dismiss or a Banish: 7/20 of it)
    over_time = {**view, "unit": "hp_total", "lasting": 60, "magnitude": 60, "duration_ticks": 20}  # (a total of 60 over twenty ticks: a lasting part with an end is held to one copy up, as before)
    assert value_module.damage_value(over_time, PPM, J) == min(PPM * 60 * LANDING, 60 * LANDING * 10 / 20)


def test_a_proc_that_never_fires_is_worth_nothing_even_for_a_permanent_spell():
    """H5: a permanent spell is up for ever once a proc has started it, so a rate of 0 or below, which starts none, makes it worth 0 (it was valued as always up). A real Rate line is within +-75 percent
    (8 records of the catalog), which leaves a rate above 0, so nothing in the data is changed; the rate of a line at -100 percent or under is 0, never a negative number."""
    from trioforge.effects import value as value_module

    assert value_module.proc_per_minute(J, -75) == PPM / 4 > 0
    assert value_module.proc_per_minute(J, -100) == 0 and value_module.proc_per_minute(J, -150) == 0 and value_module.proc_per_minute(J, 0) == PPM
    view = {"category": "dot", "once": 10, "lasting": 6, "magnitude": 6, "unit": "hp_per_tick", "duration_ticks": 0, "target": 5}
    assert value_module.damage_value(view, value_module.proc_per_minute(J, -100), J) == 0
    assert value_module.damage_value(view, Fraction(0), J) == 0 and value_module.damage_value(view, Fraction(-1, 2), J) == 0
    assert value_module.damage_value(view, PPM, J) == PPM * 10 * LANDING + 60 * LANDING  # (at a rate above 0 it is as it was)
    over_time = {**view, "unit": "hp_total", "lasting": 60, "duration_ticks": 20}
    assert value_module.damage_value(over_time, Fraction(-1, 2), J) == 0


def test_the_two_parts_of_a_record_are_written_out_in_the_valuation_of_the_lists_and_the_table_alike():
    """The record keeps its parts, and the value of the solver and the score of the lists are one function of them (F2)."""
    from trioforge.effects import value as value_module

    spell = srow(1, "Venom Brand", [[1, 79, -500, 0, 100, 0], [2, 0, -50, 0, 100, 0]], dur=(4, 10))
    effects, ctx, book = world([("w1", ["PRIMARY"], "proc", "Venom Brand")], [spell])
    (effect,) = effects
    assert (effect["once"], effect["lasting"], effect["magnitude"]) == (500, 500, 1000)
    view = {"category": "dot", "once": 500, "lasting": 500, "magnitude": 1000, "duration_ticks": 10, "target": 5}
    assert value_module.damage_value(view, PPM, J) == score.effect_value(effect, ctx, book, J, TRIO)


def damage_and_kind(kind_row):
    """The strong damage proc that sets the scale of the others (200: the 90th percentile of a world with one damage proc), and ``kind_row``."""
    return [damage(1, "Scale Brand", 200), kind_row]


def test_a_proc_that_is_not_damage_counts_its_share_of_the_scale_times_the_landing():
    slow = srow(2, "Drag Brand", [[1, 11, 70, 0, 100, 0]])  # a 30 percent slow
    items = [("w1", ["PRIMARY"], "proc", "Scale Brand"), ("w2", ["PRIMARY"], "proc", "Drag Brand")]
    assert value_of(items, damage_and_kind(slow), "Drag Brand") == PPM * Fraction(1, 2) * 200 * LANDING  # proc_value slow 1/2 of the scale, and the landing like any kind


def test_a_proc_of_a_kind_a_class_of_the_trio_casts_at_least_as_strong_is_cut():
    slow = srow(2, "Drag Brand", [[1, 11, 70, 0, 100, 0]])
    items = [("w1", ["PRIMARY"], "proc", "Scale Brand"), ("w2", ["PRIMARY"], "proc", "Drag Brand")]
    own = srow(3, "Own Tangle", [[1, 11, 70, 0, 100, 0]], levels={"WAR": 20})  # the same 30 percent: at least as strong
    cut = value_of(items, [*damage_and_kind(slow), own], "Drag Brand")
    assert cut == PPM * Fraction(1, 2) * 200 * LANDING * Fraction(3, 20)
    weaker = srow(3, "Own Tangle", [[1, 11, 80, 0, 100, 0]], levels={"WAR": 20})  # 20 percent: weaker than the proc, no cut
    assert value_of(items, [*damage_and_kind(slow), weaker], "Drag Brand") == PPM * Fraction(1, 2) * 200 * LANDING
    elsewhere = srow(3, "Own Tangle", [[1, 11, 70, 0, 100, 0]], levels={"CLR": 20})  # a class outside the trio
    assert value_of(items, [*damage_and_kind(slow), elsewhere], "Drag Brand") == PPM * Fraction(1, 2) * 200 * LANDING


def test_a_haste_proc_keeps_the_haste_cut_when_the_trio_has_a_haste_buff():
    haste = srow(2, "Swift Brand", [[1, 11, 130, 0, 100, 0]], ben=1)
    items = [("w1", ["PRIMARY"], "proc", "Scale Brand"), ("w2", ["PRIMARY"], "proc", "Swift Brand")]
    buff = srow(3, "Quicken", [[1, 11, 150, 0, 100, 0]], ben=1, levels={"ENC": 40})  # a haste buff of 50 percent for a player
    assert value_of(items, [*damage_and_kind(haste), buff], "Swift Brand") == PPM * Fraction(6, 10) * 200 * LANDING * Fraction(1, 10)
    assert value_of(items, damage_and_kind(haste), "Swift Brand") == PPM * Fraction(6, 10) * 200 * LANDING  # no haste class, no cut (and the own cut is not used on it)


# ---- the marks of an unverified record ------------------------------------------------------------------------------------------------------------------------


def test_a_verified_record_counts_in_full_and_an_ambiguous_one_at_its_smaller_candidate():
    items = [("w1", ["PRIMARY"], "proc", "Twin Brand")]
    one = [damage(1, "Twin Brand", 300), damage(2, "Twin Brand", 100)]  # two spells of one name: the lowest id is the pick, and the record is marked ambiguous
    effects, ctx, book = world(items, one)
    assert effects[0]["unverified"] == ["ambiguous"] and effects[0]["magnitude"] == 300
    assert score.effect_value(effects[0], ctx, book, J, TRIO) == PPM * 100 * LANDING  # the smaller of the two spells
    flipped = [damage(1, "Twin Brand", 100), damage(2, "Twin Brand", 300)]
    assert value_of(items, flipped) == PPM * 100 * LANDING


def test_an_inferred_record_counts_nothing():
    # an effect with no trigger wording (kind other) whose spell is offensive, on a weapon, is a proc inferred
    inferred = ("w1", ["PRIMARY"], "other", "Guess Brand", "Effect: Guess Brand")
    effects, ctx, book = world([inferred], [damage(1, "Guess Brand", 300)])
    proc = [e for e in effects if e.get("kind_inferred") == "proc"]
    assert proc and proc[0]["unverified"] == ["inferred"]
    assert score.effect_value(proc[0], ctx, book, J, TRIO) == 0
    assert score.proc_table(effects, ctx, book, J, TRIO) is None


def test_a_record_the_rules_name_as_described_differently_counts_nothing_unless_the_rule_lets_it_count():
    named = dataclasses.replace(J, unverified_names=frozenset({"Moonlit Brand"}))
    items = [("w1", ["PRIMARY"], "proc", "Moonlit Brand")]
    effects, ctx, book = world(items, [damage(1, "Moonlit Brand", 300)], named)
    assert effects[0]["unverified"] == ["description"]
    assert score.effect_value(effects[0], ctx, book, named, TRIO) == 0
    lenient = dataclasses.replace(named, proc_score_kinds=frozenset({"ambiguous", "description"}))
    assert score.effect_value(effects[0], ctx, book, lenient, TRIO) == PPM * 300 * LANDING


def test_an_ambiguous_and_inferred_record_counts_nothing_as_the_unlisted_mark_decides():
    both = ("w1", ["PRIMARY"], "other", "Twin Guess", "Effect: Twin Guess")
    effects, ctx, book = world([both], [damage(1, "Twin Guess", 300), damage(2, "Twin Guess", 100)])
    proc = [e for e in effects if e.get("kind_inferred") == "proc"][0]
    assert proc["unverified"] == ["ambiguous", "inferred"] and score.effect_value(proc, ctx, book, J, TRIO) == 0


def test_a_name_with_no_spell_counts_nothing():
    effects, ctx, book = world([("w1", ["PRIMARY"], "proc", "Lost Brand")], [damage(1, "Other", 300)])
    assert effects[0]["category"] == "unresolved" and score.effect_value(effects[0], ctx, book, J, TRIO) == 0


# ---- the table of a trio ------------------------------------------------------------------------------------------------------------------------------------------


def test_the_table_lists_the_donors_the_trio_can_wear_with_the_classes_of_the_trio_that_can_use_them():
    items = [
        sitem("w-a", ["PRIMARY"], "proc", "Blazing Brand", classes=("WAR",)),
        sitem("w-b", ["PRIMARY", "SECONDARY"], "proc", "Blazing Brand", classes=("WAR", "CLR", "SHM")),
        sitem("w-cleric", ["PRIMARY"], "proc", "Blazing Brand", classes=("CLR",)),  # no class of the trio
        sitem("w-charm", ["CHARM"], "proc", "Blazing Brand"),  # a slot the kit has no place for: not a donor
    ]
    effects, ctx, book = world(items, [damage(1, "Blazing Brand", 200)])
    table = score.proc_table(effects, ctx, book, J, TRIO)
    assert [(d.key, sorted(d.classes), d.primary_only) for d in table.donors] == [("w-a", ["WAR"], True), ("w-b", ["SHM", "WAR"], False)]
    assert table.socket_tier == 4 and table.trio == TRIO and table.effects[0].name == "Blazing Brand"


def test_a_donor_says_whether_its_item_is_lore_and_the_table_counts_one_copy_of_a_lore_item_and_two_of_another():
    spell = damage(1, "Blazing Brand", 200)
    effects, ctx, book = world([sitem(k, ["PRIMARY"], "proc", "Blazing Brand") for k in ("w-a", "w-b")], [spell])
    table = score.proc_table(effects, ctx, book, J, TRIO, lore={"w-a"})
    assert [(d.key, d.lore) for d in table.donors] == [("w-a", True), ("w-b", False)]
    assert (table.copies("w-a"), table.copies("w-b"), table.copies("anything else")) == (1, 2, 2)


def test_a_donor_that_needs_a_required_level_above_the_cap_is_no_donor():
    effects, ctx, book = world(
        [sitem("w-a", ["PRIMARY"], "proc", "Blazing Brand", "Effect: Blazing Brand (Combat) req. level 55")], [damage(1, "Blazing Brand", 200)]
    )
    assert score.proc_table(effects, ctx, book, J, TRIO) is None


def test_the_rules_are_read_not_written_into_the_code():
    other = dataclasses.replace(J, proc_landing=0.5, proc_dex=170, proc_ppm={"dex_divisor": 170, "base": 0.5})
    items = [("w1", ["PRIMARY"], "proc", "Blazing Brand")]
    assert value_of(items, [damage(1, "Blazing Brand", 200)], j=other) == Fraction(3, 2) * 200 * Fraction(1, 2)


@pytest.mark.parametrize("rule", ["effects.proc_per_minute", "effects.proc_reference_dex", "effects.proc_landing", "effects.proc_own_cut", "effects.proc_score_kinds"])
def test_the_new_rules_are_judgments_with_the_seal_model(rule):
    from trioforge import rules

    assert rules.load().seal(rule) == "model"


def test_an_ambiguous_record_whose_name_has_no_candidate_spell_in_the_book_counts_nothing():
    # the record was made from a book that has two spells of the name (so it is marked ambiguous and has the pick's own view); valued against a book that has none of that name, it matches
    # no spell, and the rule is that such a record counts 0: it must not fall back to the record's own view and count in full
    one = [damage(1, "Twin Brand", 300), damage(2, "Twin Brand", 100)]
    effects, ctx, book = world([("w1", ["PRIMARY"], "proc", "Twin Brand")], one)
    (record,) = effects
    assert record["unverified"] == ["ambiguous"] and record["magnitude"] == 300 and score.effect_value(record, ctx, book, J, TRIO) == PPM * 100 * LANDING  # (the smaller candidate, as before)
    other = sp.SpellBook([damage(3, "Some Other Brand", 500)], 50)
    assert score.effect_value(record, ctx, other, J, TRIO) == 0
    assert score.effect_values(effects, ctx, other, J, TRIO) == {}


def test_with_the_data_of_today_every_ambiguous_proc_record_has_a_candidate_spell():
    """The path above is not reached by the shipped data: the mark is made from the same-named spells of the book, so a record that has it has candidates. Held on the committed catalog
    and spell file, so that a change of either that makes the path reachable shows."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    items = json.loads((root / "derived" / "catalog.json").read_text(encoding="utf-8"))["items"]
    book = sp.SpellBook.load(root / "derived" / "client" / "effect-spells.json")
    carriers = [item for item in items if item["evidence"]["level"] == "wiki" and item.get("effects")]
    effects, _ = dn.build_effects(carriers, book, J)
    ambiguous = [e for e in effects if dn.kind_of(e) == "proc" and "ambiguous" in (e.get("unverified") or ())]
    assert ambiguous  # (the data has some: the test looks at something)
    assert all(score._candidate_views(e, book, J) for e in ambiguous), [e["name"] for e in ambiguous if not score._candidate_views(e, book, J)]
