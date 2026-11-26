"""Tests for the spell side of the effects layer: the category of a spell, focus limits, the partial credit of a focus above its maximum level, and the
choice among spells of one name. The first part ports the tests of the private analysis tool (small synthetic spells, no game files)."""

import pytest

from trioforge.effects import judgment
from trioforge.effects import spells as sp
from trioforge.effects.layer import focus_coverage

J = judgment.default()


def fx(spa, base=0, limit=0, formula=100, maximum=0, value=None):
    return {"slot": 1, "spa": spa, "base": base, "limit": limit, "formula": formula, "max": maximum, "value": base if value is None else value}


def spell(effects, name="Synthetic", beneficial=1, duration_ticks=0, permanent=False, cast_ms=2000, target=5, resist=0, levels=None, mana=10, sid=1):
    return {
        "id": sid, "name": name, "cast_ms": cast_ms, "mana": mana, "duration_ticks": duration_ticks, "permanent": permanent, "beneficial": beneficial,
        "resist": resist, "target": target, "levels": levels or {"CLR": 10}, "effects": effects,
    }  # fmt: skip


def classify(*args, **kwargs):
    return sp.classify_spell(spell(*args, **kwargs), J)


# ---- names ---------------------------------------------------------------------------------------------------------


def test_parse_family_roman_tier():
    assert sp.parse_family("Spell Haste II") == ("Spell Haste", 2)
    assert sp.parse_family("Improved Damage III") == ("Improved Damage", 3)
    assert sp.parse_family("Minor Improved Damage I") == ("Minor Improved Damage", 1)


def test_parse_family_no_tier():
    assert sp.parse_family("Minion of Fire") == ("Minion of Fire", None)
    assert sp.parse_family("Wind Resonance 14") == ("Wind Resonance 14", None)
    assert sp.strip_number("Wind Resonance 14") == "Wind Resonance"


# ---- focus -----------------------------------------------------------------------------------------------------------


def focus_damage(max_level=60, instant=1, spell_type=0):
    return spell([fx(124, 1, 20), fx(134, max_level, 5), fx(137, 0), fx(141, instant), fx(138, spell_type), fx(136, -4), fx(311)], name="Improved Damage III")


def test_classify_focus_improved_damage():
    f = sp.classify_focus(focus_damage())
    assert f["kind"] == "improved_damage"
    assert (f["min_pct"], f["max_pct"]) == (1, 20)
    assert f["limits"]["max_level"] == 60 and f["limits"]["instant"] == 1 and f["limits"]["spell_type"] == 0


def test_classify_focus_haste_and_duration():
    f = sp.classify_focus(spell([fx(127, 33), fx(134, 44, 5), fx(140, 5), fx(143, 2000), fx(138, 0), fx(137, 0)]))
    assert f["kind"] == "spell_haste" and f["min_pct"] == f["max_pct"] == 33
    assert f["limits"]["min_duration"] == 5 and f["limits"]["min_cast_ms"] == 2000
    f = sp.classify_focus(spell([fx(128, 15), fx(134, 20, 5)]))
    assert f["kind"] == "extended_duration" and f["max_pct"] == 15


def test_classify_focus_not_a_focus():
    assert sp.classify_focus(spell([fx(13, 1)])) is None


def test_focus_applies_direct_damage_only():
    f = sp.classify_focus(focus_damage())
    nuke = spell([fx(0, -200)], beneficial=0, duration_ticks=0)
    dot = spell([fx(0, -20)], beneficial=0, duration_ticks=12)
    heal = spell([fx(0, 200)], beneficial=1)
    assert sp.focus_applies(f["limits"], nuke, 40)
    assert not sp.focus_applies(f["limits"], dot, 40)  # not instant
    assert not sp.focus_applies(f["limits"], heal, 40)  # beneficial


def test_focus_applies_excluded_target_and_effect():
    f = sp.classify_focus(focus_damage())
    ae = spell([fx(0, -200)], beneficial=0, target=4)  # point-blank AE is excluded by 136:-4
    assert not sp.focus_applies(f["limits"], ae, 30)
    ex = sp.classify_focus(spell([fx(128, 15), fx(138, 1), fx(137, -40)]))
    inv = spell([fx(40, 1)], duration_ticks=20)
    assert not sp.focus_applies(ex["limits"], inv, 30)


def test_focus_applies_min_duration_and_cast_time():
    f = sp.classify_focus(spell([fx(127, 33), fx(140, 5), fx(143, 2000), fx(138, 0)]))
    slow_dot = spell([fx(0, -5)], beneficial=0, duration_ticks=10, cast_ms=3000)
    quick_dot = spell([fx(0, -5)], beneficial=0, duration_ticks=10, cast_ms=500)
    short = spell([fx(0, -5)], beneficial=0, duration_ticks=2, cast_ms=3000)
    assert sp.focus_applies(f["limits"], slow_dot, 30)
    assert not sp.focus_applies(f["limits"], quick_dot, 30)
    assert not sp.focus_applies(f["limits"], short, 30)


def test_focus_type_is_the_effect_id():
    haste = sp.classify_focus(spell([fx(127, 15), fx(134, 44, 5)]))
    afflict = sp.classify_focus(spell([fx(127, 33), fx(140, 5), fx(138, 0)]))
    dmg = sp.classify_focus(focus_damage())
    assert sp.focus_type(haste) == sp.focus_type(afflict) != sp.focus_type(dmg)


# ---- the focus level penalty: partial credit (finding 1 of the review) -------------------------------------------------------------------------


def spell_haste_two():
    """Spell Haste II as the client has it: 15 percent, spells to level 44, 5 percent lost for each level above."""
    return sp.classify_focus(spell([fx(127, 15), fx(134, 44, 5), fx(143, 2000)], name="Spell Haste II"))


def test_a_level_49_spell_keeps_75_percent_of_a_focus_capped_at_44_with_5_percent_a_level():
    f = spell_haste_two()
    nuke = spell([fx(0, -200)], beneficial=0, cast_ms=3000)
    assert sp.focus_weight(f["limits"], nuke, 44) == 1.0
    assert sp.focus_weight(f["limits"], nuke, 49) == pytest.approx(0.75)
    assert sp.focus_weight(f["limits"], nuke, 50) == pytest.approx(0.70)


def test_a_focus_loses_everything_20_levels_above_its_maximum_at_5_percent_and_a_maximum_with_no_percent_is_a_wall():
    nuke = spell([fx(0, -200)], beneficial=0, cast_ms=3000)
    f = spell_haste_two()
    assert sp.focus_weight(f["limits"], nuke, 64) == 0.0
    wall = sp.classify_focus(spell([fx(127, 15), fx(134, 44, 0)]))
    assert sp.focus_weight(wall["limits"], nuke, 44) == 1.0
    assert sp.focus_weight(wall["limits"], nuke, 45) == 0.0


def test_the_other_limits_still_rule_a_spell_out_whatever_its_level():
    f = spell_haste_two()
    quick = spell([fx(0, -200)], beneficial=0, cast_ms=500)  # cast time under the 2.0 s the focus needs
    assert sp.focus_weight(f["limits"], quick, 30) == 0.0


def test_coverage_gives_partial_credit_to_a_spell_above_the_focus_maximum():
    nuke = spell([fx(0, -200)], beneficial=0, cast_ms=3000, levels={"WIZ": 49}, sid=7)
    effect = {"id": "e000", "focus": spell_haste_two()}
    coverage = focus_coverage([effect], [nuke], {7: "damage"}, J)
    assert coverage["e000"]["WIZ"]["share"] == pytest.approx(0.75)
    assert coverage["e000"]["WIZ"]["n"] == 1 and coverage["e000"]["WIZ"]["of"] == 1
    below = spell([fx(0, -200)], beneficial=0, cast_ms=3000, levels={"WIZ": 40}, sid=8)
    assert focus_coverage([effect], [below], {8: "damage"}, J)["e000"]["WIZ"]["share"] == pytest.approx(1.0)


def test_limit_text_says_weaker_above_the_maximum_level():
    text = sp.limit_text(spell_haste_two())
    assert "up to spell level 44 (weaker above)" in text
    assert "cast time of 2 s or more" in text
    assert sp.limit_text(sp.classify_focus(spell([fx(128, 15)]))) == "all spells"
    assert sp.limit_text(sp.classify_focus(focus_damage())).startswith("detrimental and instant spells")


# ---- the category of a spell ---------------------------------------------------------------------------------------------


def test_classify_direct_damage_dot_and_heal():
    c = classify([fx(0, -250)], beneficial=0)
    assert c["category"] == "damage" and c["magnitude"] == 250
    assert classify([fx(0, -25)], beneficial=0, duration_ticks=12)["category"] == "dot"
    c = classify([fx(0, 300)])
    assert c["category"] == "heal" and c["magnitude"] == 300
    assert classify([fx(0, 20)], duration_ticks=30)["category"] == "heal_over_time"


def test_classify_lifetap():
    assert classify([fx(0, -100)], beneficial=0, target=13)["category"] == "lifetap"


def test_classify_haste_vs_slow_and_runspeed_vs_snare():
    assert classify([fx(11, 130)], duration_ticks=60)["category"] == "haste"
    assert classify([fx(11, 70)], beneficial=0, duration_ticks=60)["category"] == "slow"
    assert classify([fx(3, 40)], duration_ticks=60)["category"] == "run_speed"
    assert classify([fx(3, -40)], beneficial=0, duration_ticks=60)["category"] == "snare"


def test_classify_utility_and_cc():
    assert classify([fx(57, 1)], duration_ticks=100)["category"] == "levitate"
    assert classify([fx(12, 1)], duration_ticks=100)["category"] == "invisibility"
    assert classify([fx(21, 4000)], beneficial=0)["category"] == "crowd_control"
    assert classify([fx(15, 100)])["category"] == "mana"
    assert classify([fx(32, 1)])["category"] == "summon_item"


def test_classify_stat_buff_and_resist_debuff():
    assert classify([fx(1, 20), fx(4, 10)], duration_ticks=100)["category"] == "buff_stats"
    assert classify([fx(46, -20), fx(50, -20)], beneficial=0, duration_ticks=20)["category"] == "debuff"


def test_classify_hot_spa_and_proc_buff():
    assert classify([fx(100, 20)], duration_ticks=30)["category"] == "heal_over_time"
    assert classify([fx(85, 123)], duration_ticks=30)["category"] == "proc_buff"


def test_hp_buff_with_current_hp_is_a_buff_not_a_heal():
    assert classify([fx(69, 224), fx(79, 224)], duration_ticks=450)["category"] == "buff_stats"
    assert classify([fx(0, 200)])["category"] == "heal"


def test_dot_magnitude_is_total_over_duration():
    c = classify([fx(0, -10)], beneficial=0, duration_ticks=12)
    assert c["magnitude"] == 120 and c["unit"] == "hp_total"


# ---- a spell with a direct hit and a lasting part is sized by its whole (E2) ------------------------------------------------------------------


def test_a_direct_hit_with_a_lasting_part_is_sized_by_the_whole():
    """Strong Poison has the shape: SPA 79 (one time) and SPA 0 (each tick). The size is the one-time part plus the lasting part for every tick, as :func:`sp._over_time` reads a lasting spell."""
    c = classify([fx(79, -30), fx(0, -14)], beneficial=0, duration_ticks=20)
    assert c == {"category": "dot", "magnitude": 310, "unit": "hp_total", "once": 30, "lasting": 280}  # 30 + 14 x 20, and not the larger single number (30); the two parts are kept apart (F1)
    c = classify([fx(0, -14), fx(79, -30)], beneficial=0, duration_ticks=20)
    assert c == {"category": "dot", "magnitude": 310, "unit": "hp_total", "once": 30, "lasting": 280}  # (the order of the effects makes no difference)


def test_the_parts_of_a_spell_add_up_by_what_they_are():
    assert classify([fx(79, -30), fx(79, -20)], beneficial=0, duration_ticks=20) == {"category": "damage", "magnitude": 50, "unit": "hp", "once": 50, "lasting": 0}  # (two one-time parts: a direct hit of both)
    assert classify([fx(0, -10), fx(0, -4)], beneficial=0, duration_ticks=10) == {"category": "dot", "magnitude": 140, "unit": "hp_total", "once": 0, "lasting": 140}  # (two lasting parts: each for every tick)
    assert classify([fx(79, 40), fx(0, 5)], duration_ticks=12) == {"category": "heal_over_time", "magnitude": 100, "unit": "hp_total", "once": 40, "lasting": 60}  # (a heal with a lasting part is a heal over time of the whole)
    assert classify([fx(0, -100), fx(0, -50)], beneficial=0) == {"category": "damage", "magnitude": 150, "unit": "hp", "once": 150, "lasting": 0}  # (an instant spell: every part is one time)


def test_a_permanent_spell_keeps_its_number_for_each_tick_and_its_one_time_part_apart():
    """F1: a number of each tick and a number of one time are not added under the unit hp_per_tick: the magnitude is the tick's, the one-time part is its own field."""
    c = classify([fx(0, -6), fx(79, -10)], beneficial=0, permanent=True)
    assert c == {"category": "dot", "magnitude": 6, "unit": "hp_per_tick", "once": 10, "lasting": 6}
    assert classify([fx(0, -6)], beneficial=0, permanent=True) == {"category": "dot", "magnitude": 6, "unit": "hp_per_tick", "once": 0, "lasting": 6}


def test_the_kind_of_a_mixed_spell_follows_its_larger_part():
    """H4: a spell with a one-time part and a lasting part is of the kind of the larger of the two (the one-time total against the lasting total, a tie to the one-time kind); the two parts stay apart as F1
    made them and the size is still the whole. The Cleric's two fast heals have the shape of the first two cases: 310 at once and 165 over one tick, 640 and 260 (65 and 71 percent direct)."""
    heal = classify([fx(79, 310), fx(100, 165)], duration_ticks=1, cast_ms=1500)
    assert heal == {"category": "heal", "magnitude": 475, "unit": "hp_total", "once": 310, "lasting": 165}  # (a heal that lasts a tick is a heal)
    assert classify([fx(79, 640), fx(100, 260)], duration_ticks=1, cast_ms=1500)["category"] == "heal"
    assert classify([fx(79, 40), fx(0, 5)], duration_ticks=12)["category"] == "heal_over_time"  # (40 at once and 60 over time: the lasting part is larger)
    assert classify([fx(79, 50), fx(100, 5)], duration_ticks=10)["category"] == "heal"  # (a tie of 50 and 50: the one-time kind)
    assert classify([fx(79, -155), fx(0, -78)], beneficial=0, duration_ticks=1)["category"] == "damage"  # (a hit of 155 and 78 over one tick: a direct hit)
    assert classify([fx(79, -30), fx(0, -14)], beneficial=0, duration_ticks=20)["category"] == "dot"  # (Strong Poison: 30 against 280)
    assert classify([fx(79, -500), fx(0, -50)], beneficial=0, duration_ticks=5) == {"category": "damage", "magnitude": 750, "unit": "hp_total", "once": 500, "lasting": 250}  # (the parts and the size are as they were)
    assert classify([fx(0, -6), fx(79, -10)], beneficial=0, permanent=True)["category"] == "dot"  # (a permanent spell has no end to its total: it is over time whatever its one-time part)
    assert classify([fx(0, -10), fx(79, -500)], beneficial=0, target=13, duration_ticks=10)["category"] == "lifetap"  # (a lifetap is a lifetap)


def test_the_sign_of_a_mixed_spell_is_that_of_its_larger_whole():
    c = classify([fx(79, -30), fx(0, 5)], duration_ticks=20)  # 30 down once, 100 up over the duration
    assert c["category"] == "heal_over_time" and c["magnitude"] == 100
    c = classify([fx(79, -300), fx(0, 5)], beneficial=0, duration_ticks=20)
    assert c["category"] == "damage" and c["magnitude"] == 300  # (the lasting part of the other sign is not netted off: it is a different effect)


def test_a_lifetap_and_the_hit_points_spent_for_mana_keep_their_rules_with_a_mixed_spell():
    assert classify([fx(0, -100), fx(79, -20)], beneficial=0, target=13) == {"category": "lifetap", "magnitude": 120, "unit": "hp", "once": 120, "lasting": 0}
    assert classify([fx(0, -10), fx(79, -20)], beneficial=0, target=13, duration_ticks=10) == {"category": "lifetap", "magnitude": 120, "unit": "hp_total", "once": 20, "lasting": 100}  # (a lifetap with a lasting part: the parts apart, F1)
    assert classify([fx(0, -50), fx(15, 16)], target=6)["category"] == "mana"


def test_unknown_spa_is_other():
    assert classify([fx(9999, 1)])["category"] == "other"


def test_hate_category():
    assert classify([fx(192, 100)], beneficial=0)["category"] == "hate"
    assert classify([fx(0, -50), fx(192, 100)], beneficial=0)["category"] == "damage"  # damage plus hate stays damage


# ---- hit points spent for mana (finding 2 of the review) -----------------------------------------------------------------------------------


def test_a_self_cast_that_spends_hit_points_for_mana_is_mana_not_damage():
    cannibalize = classify([fx(0, -50), fx(15, 16)], target=6)  # the client's Cannibalize: 50 hit points for 16 mana
    assert cannibalize["category"] == "mana" and cannibalize["magnitude"] == 16 and cannibalize["unit"] == "mana"


def test_the_same_effects_on_another_target_are_not_a_mana_spell():
    assert classify([fx(0, -50), fx(15, 16)], target=5, beneficial=0)["category"] == "damage"
    assert classify([fx(0, -50)], target=6, beneficial=0)["category"] == "damage"  # a self-cast that only costs hit points has no mana to count


def test_mana_without_hit_points_stays_mana_and_a_drain_of_endurance_is_no_damage():
    assert classify([fx(189, -200), fx(15, 100)], target=6)["category"] == "mana"  # Mana Convert spends endurance


def test_the_real_cannibalize_is_mana():
    rows = {row["id"]: row for row in sp.SpellBook.load().rows}
    for spell_id in (265, 754):  # Cannibalize and Cannibalize II of the Shaman (the rows carry no name: nothing needs it)
        assert rows[spell_id]["fx"][0][:3] == [1, 0, rows[spell_id]["fx"][0][2]] and rows[spell_id]["fx"][0][2] < 0 and rows[spell_id]["lv"].keys() == {"SHM"}
        assert sp.classify_spell(sp.spell_from_row(rows[spell_id], 50), J)["category"] == "mana"


def test_the_self_casts_that_spend_hit_points_for_mana_are_these_six_class_spells():
    moved = {s["id"] for s in sp.SpellBook.load().class_spells() if sp.classify_spell(s, J)["category"] == "mana" and any(e["spa"] == 0 for e in s["effects"])}
    assert moved == {265, 754, 641, 642, 643, 644}  # Cannibalize I and II, and the Necromancer's Dark Pact, Allure of Death, Call of Bones and Lich


def test_a_dispel_counts_the_buffs_it_strips():
    one = classify([fx(27, 1)])
    four = classify([fx(27, 4), fx(27, 4), fx(27, 4), fx(27, 4)])
    assert one["category"] == four["category"] == "dispel"
    assert (one["magnitude"], four["magnitude"]) == (1, 4)


# ---- choosing among spells of one name ------------------------------------------------------------------------------------------


def test_pick_spell_proc_prefers_detrimental_classic_id():
    buff = spell([fx(1, 10)], duration_ticks=30, sid=100)
    nuke = spell([fx(0, -50)], beneficial=0, sid=500)
    npc = spell([fx(0, -186000)], beneficial=0, sid=32425)
    assert sp.pick_spell([buff, nuke], "proc")[0]["id"] == 500
    assert sp.pick_spell([buff, npc], "proc")[0]["id"] == 100  # NPC-scale damage is not trusted
    assert sp.pick_spell([buff, nuke], "click")[0]["id"] == 100  # clicks: lowest id


def test_pick_spell_worn_prefers_permanent():
    a = spell([fx(1, 5)], duration_ticks=30, sid=10)
    b = spell([fx(65, 1)], permanent=True, duration_ticks=0, sid=20)
    assert sp.pick_spell([a, b], "worn")[0]["id"] == 20


def test_pick_spell_reports_ambiguity():
    a = spell([fx(0, -5)], beneficial=0, sid=1)
    b = spell([fx(0, -9)], beneficial=0, sid=2)
    assert sp.pick_spell([a, b], "proc")[1] is True
    assert sp.pick_spell([a], "proc")[1] is False


# ---- what a class casts -----------------------------------------------------------------------------------------------------------------


def test_spell_action_kind_for_class_needs():
    nuke = spell([fx(0, -100)], beneficial=0, levels={"WIZ": 40})
    heal = spell([fx(0, 100)], levels={"CLR": 40})
    buff = spell([fx(1, 10)], duration_ticks=100, levels={"CLR": 40})
    prof = sp.class_profile([nuke, heal, buff], "CLR", J)
    assert prof["total"] == 2 and prof["by_category"] == {"heal": 1, "buff_stats": 1}
    assert sp.class_profile([nuke, heal, buff], "WIZ", J)["by_category"] == {"damage": 1}


def test_class_profile_respects_cap():
    assert sp.class_profile([spell([fx(0, -100)], beneficial=0, levels={"WIZ": 55})], "WIZ", J)["total"] == 0


def test_haste_buff_provider():
    group = spell([fx(11, 150, value=150)], duration_ticks=100, target=41, levels={"ENC": 40})
    pet = spell([fx(11, 150, value=150)], duration_ticks=100, target=14, levels={"MAG": 40})
    weak = spell([fx(11, 110, value=110)], duration_ticks=100, target=6, levels={"PAL": 40})
    assert sp.has_haste_buff([group, pet, weak], "ENC", J)
    assert not sp.has_haste_buff([group, pet, weak], "MAG", J)  # pet-only haste does not count
    assert not sp.has_haste_buff([group, pet, weak], "PAL", J)  # under 30 percent does not count


# ---- the spell file -----------------------------------------------------------------------------------------------------------


def row(sid, name, effects, levels=None, **extra):
    base = {"id": sid, "name": name, "cast_ms": 2000, "mana": 10, "dur": [0, 0], "ben": 0, "res": 0, "tgt": 5, "lv": levels or {}, "fx": effects}
    return {**base, **extra}


def test_a_spell_record_applies_the_client_formulas_at_the_level_it_is_cast_at():
    r = row(1, "Test", [[1, 0, -10, 0, 103, 200], [2, 134, 44, 5, 0, 0]])  # formula 103: base + 2 x level
    at50, at20 = sp.spell_from_row(r, 50), sp.spell_from_row(r, 20)
    assert at50["effects"][0]["value"] == -min(110, 200) and at20["effects"][0]["value"] == -50
    assert at50["effects"][1]["value"] is None  # a limit has no value
    assert at50["duration_ticks"] == 0 and at50["permanent"] is False
    assert sp.spell_from_row({**r, "dur": [50, 0]}, 50)["permanent"] is True


def test_the_spell_book_finds_rows_by_name_and_keeps_the_class_spells_up_to_the_cap():
    rows = [row(1, "A", [], {"WIZ": 40}), row(2, "A", [], {"WIZ": 60}), row(3, "B", [], {})]
    book = sp.SpellBook(rows, 50)
    assert [r["id"] for r in book.by_name["A"]] == [1, 2]
    assert [s["id"] for s in book.class_spells()] == [1]  # level 60 is above the cap; B has no class
    assert book.class_spells() is book.class_spells()


def test_the_real_spell_file_loads_and_says_which_client_file_it_came_from():
    book = sp.SpellBook.load()
    assert book.cap == 50 and len(book.rows) > 1000
    assert book.source_sha256 and len(book.source_sha256) == 64
    assert "Spell Haste II" in book.by_name or "Cancel Magic" in book.by_name


# ---- the fix round: the skill limit of the instrument foci (review finding 4) ------------------------------------------------------------------------------


def instrument_focus(skill):
    return sp.classify_focus(spell([fx(413, 150), fx(411, 256), fx(414, skill)], name="Resonance"))


def test_an_instrument_focus_covers_only_the_songs_of_its_own_skill():
    brass = instrument_focus(12)
    assert brass["limits"]["skill"] == 12
    brass_song = {**spell([fx(0, 100)], levels={"BRD": 30}), "skill": 12}
    wind_song = {**spell([fx(0, 100)], levels={"BRD": 30}), "skill": 54}
    nuke = spell([fx(0, -200)], beneficial=0)  # a spell that records no skill
    assert sp.focus_weight(brass["limits"], brass_song, 30) == 1.0
    assert sp.focus_weight(brass["limits"], wind_song, 30) == 0.0
    assert sp.focus_weight(brass["limits"], nuke, 30) == 0.0
    assert not sp.focus_applies(brass["limits"], wind_song, 30)


def test_a_focus_with_no_skill_limit_is_not_held_to_a_skill():
    f = sp.classify_focus(focus_damage())
    assert f["limits"]["skill"] is None
    assert sp.focus_weight(f["limits"], {**spell([fx(0, -200)], beneficial=0), "skill": 99}, 30) == 1.0


def test_the_derived_rows_carry_the_skill_and_the_bards_songs_are_the_five_instrument_and_singing_skills():
    book = sp.SpellBook.load()
    songs = [r for r in book.rows if r["lv"] and set(r["lv"]) == {"BRD"}]
    assert len(songs) >= 60 and {r["sk"] for r in songs} == {12, 41, 49, 54, 70}
    rows = {r["name"]: r for r in book.rows if r["name"].endswith(("Resonance 15", "Resonance 14", "Resonance 11"))}
    for name, skill in (("Brass Resonance 15", 12), ("Wind Resonance 14", 54), ("Percussion Resonance 14", 70), ("String Resonance 11", 49)):
        focus = sp.classify_focus(sp.spell_from_row(rows[name], 50))
        assert focus["limits"]["skill"] == skill
        covered = {s["skill"] for s in book.class_spells() if sp.focus_weight(focus["limits"], s, s["levels"].get("BRD", 0) or 50) > 0}
        assert covered == {skill}  # only songs of its own instrument
