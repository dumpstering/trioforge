"""Tests for the ranked lists of the effects layer, on the real catalog and the client's spell text (``derived/``): the order the analysis found for the two example
trios, the order the three fixes and the dispel change give, one focus for each stacking type, the dispel constant, and the guards."""

import dataclasses
import json
from fractions import Fraction
from itertools import combinations
from pathlib import Path

import pytest

from trioforge.classes import CLASS_CODES
from trioforge.effects import donors as dn
from trioforge.effects import files, judgment, layer
from trioforge.effects import spells as sp
from trioforge.model.roles import roles_for

REPO = Path(__file__).resolve().parents[2]
J = judgment.default()


@pytest.fixture(scope="module")
def built():
    catalog = json.loads((REPO / "derived" / "catalog.json").read_text(encoding="utf-8"))
    return files.build(catalog, sp.SpellBook.load(), J, "test")


def lists(built, slug, role, **kwargs):
    return layer.layer([c.upper() for c in slug.split("-")], role, built.ctx, **kwargs)


# ---- the example trios: the analysis' order, and what the fixes change ----------------------------------------------------------------------------------
#
# ANALYSIS is the order of the private analysis of 2026-10-22 (r2) before the review's fixes, NOW the order of this port. With every fix reverted, and the templates of that
# time, the port gave the analysis' lists for all 560 trios and every role (checked when the port was written). The differences below are the fixes' and, since the builds,
# one thing more: the mana weight of the Tank and Melee damage templates fell from 0.5 to 0.15, which moves five of the lists after the fixes (see the end of the list, and
# test_the_five_lists_that_the_mana_weight_of_the_templates_moved_are_the_earlier_ones_with_the_earlier_weight):
#
# * focus (partial credit for a spell above a focus's maximum level): Reagent Conservation III is no longer the pick, because Reagent Conservation II, the easier
#   source, now keeps most of its coverage (it is within 90 percent of III); the tier-II foci lose a few points of coverage, which moves Extended Range II above
#   Improved Healing III in clr-shd-shm and Mana Preservation II below Extended Enhancement II in pal-mnk-ber;
# * (hit points spent for mana, counted as mana: Cannibalize I and II, Dark Pact, Allure of Death, Call of Bones and Lich) alone this puts Improved Damage III over
#   Burning Affliction II in the caster role of clr-shd-shm; together with the partial credit the order is the analysis' again;
# * click (the dispel constant): Pillage Enchantment, a must-equip dispel that strips four buffs, is now in the top 3 for the caster tank and caster builds;
# * proc (Dismiss and Banish work on some targets only): Banish Summoned and Banish Undead leave the top of clr-shd-shm, and Dismiss Summoned leaves pal-mnk-ber's six;
# * carry, worn and click, and proc, after the fix round (review findings 2 and 3): the click scale is measured against the effects the lists can offer (an effect with
#   a copy that can be worn and a required level within the cap), not against every record, so the size of an effect nobody can wear no longer makes a worn effect small (Heritage of
#   Mistmoore passes See Invisible); the proc scale is measured against the same discounted size a proc score gets, so a restricted-target proc no longer sets it too high
#   (Heat Blood and Earthquake move up). Keeping the cooldown, cast time and required level with each item (finding 3 of the first review), the donor filter of the foci,
#   the click-mode flag on the donor and the per-copy kind of an unlabelled effect move no list of these trios.
# * the catalog of 2026-10-27 (the lists above were made from the catalog of 2026-10-14, and the lists of that catalog were checked to be the ones here before the data changed):
#   clr-shd-shm click (balanced, tank, melee) gains Rune III at the fourth place: Unbroken Golem Core (w72866, a new item, a must-equip Rune III that Cleric, Druid, Shaman, Necromancer,
#   Wizard, Magician and Enchanter may wear; the other wiki copy, Rod of the Protecting Winds, is Enchanter only) pushes the last place out (Lull for balanced and tank, Calm for melee);
#   clr-shd-shm proc (all four roles) loses Choke for Cleanse at the sixth place: Packmaster's Lash (w52540), the one wiki-level item with Choke, now reads "Effect: Choking (Combat)",
#   a name that is not a spell of the client (a miss), so no item of the wiki level has the proc Choke (Whip of Strangulation, w34410, is hidden).
# * the builds (2026-11-19): the mana weight of the Tank and of Melee damage fell from 0.5 to 0.15 (their attack weights rose, which moves no list: the weight of attack only scales
#   every proc of a build alike). A smaller mana weight shrinks what the lists give to mana: Mana Preservation II, scored by the share of the mana weight, falls below Reagent
#   Conservation II and Extended Enhancement II in the focus lists of the Tank and Melee damage of pal-mnk-ber and clr-shd-shm (four lists), and the bonus an instant cast gets
#   (scaled by the same share) is smaller, so Spirit of Wolf passes the instant Superior Healing in the click list of Melee damage of pal-mnk-ber (the fifth). The Balanced
#   lists are gone with the build, and the Shield caster's are new.

ANALYSIS = {
    'pal-mnk-ber/balanced/focus': ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Extended Enhancement II', 'Reagent Conservation III', 'Mana Preservation II'],
    'pal-mnk-ber/balanced/click': ['Alacrity', 'Superior Healing', 'Spirit of Wolf', 'Spirit Tap', 'Raging Strength', 'Restore Sight'],
    'pal-mnk-ber/balanced/carry': ['Walking Sleep', 'Levitate', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV', 'Breath of the Dead', 'Enduring Breath'],
    'pal-mnk-ber/balanced/worn': ['Unrighteous Bash', 'Virtuous Bash', 'See Invisible'],
    'pal-mnk-ber/balanced/proc': ["Oathbreaker's Curse", 'Cleanse', 'Haste', 'Haste', 'Earthquake', 'Dismiss Summoned'],
    'pal-mnk-ber/tank/focus': ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Extended Enhancement II', 'Reagent Conservation III', 'Mana Preservation II'],
    'pal-mnk-ber/tank/click': ['Alacrity', 'Superior Healing', 'Spirit of Wolf', 'Spirit Tap', 'Raging Strength', 'Restore Sight'],
    'pal-mnk-ber/tank/carry': ['Walking Sleep', 'Bramblecoat', 'Divine Aura', 'Levitate', 'Rune I', 'Rune IV', 'Healing', 'Breath of the Dead'],
    'pal-mnk-ber/tank/worn': ['Unrighteous Bash', 'Virtuous Bash', 'See Invisible'],
    'pal-mnk-ber/tank/proc': ["Oathbreaker's Curse", 'Cleanse', 'Haste', 'Haste', 'Earthquake', 'Dismiss Summoned'],
    'pal-mnk-ber/melee/focus': ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Extended Enhancement II', 'Reagent Conservation III', 'Mana Preservation II'],
    'pal-mnk-ber/melee/click': ['Alacrity', 'Spirit of Wolf', 'Superior Healing', 'Spirit Tap', 'Raging Strength', 'Restore Sight'],
    'pal-mnk-ber/melee/carry': ['Walking Sleep', 'Levitate', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV', 'Breath of the Dead', 'Enduring Breath'],
    'pal-mnk-ber/melee/worn': ['Unrighteous Bash', 'Virtuous Bash', 'See Invisible'],
    'pal-mnk-ber/melee/proc': ["Oathbreaker's Curse", 'Cleanse', 'Haste', 'Haste', 'Earthquake', 'Dismiss Summoned'],
    'clr-shd-shm/balanced/focus': ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Mana Preservation II', 'Reagent Conservation III', 'Extended Enhancement II'],
    'clr-shd-shm/balanced/click': ['Superior Healing', 'Spirit Tap', 'Restore Sight', 'Calm', 'Lull', 'Soothe'],
    'clr-shd-shm/balanced/carry': ['Mana Convert', 'Malaisement', 'Word of Health', 'Walking Sleep', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV'],
    'clr-shd-shm/balanced/worn': ['Unrighteous Bash', 'Heritage of Mistmoore', 'See Invisible'],
    'clr-shd-shm/balanced/proc': ['Banish Summoned', 'Banish Undead', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Cleanse'],
    'clr-shd-shm/tank/focus': ['Spell Haste II', 'Improved Damage III', 'Extended Range II', 'Improved Healing III', 'Reagent Conservation III', 'Mana Preservation II', 'Extended Enhancement II'],
    'clr-shd-shm/tank/click': ['Superior Healing', 'Spirit Tap', 'Restore Sight', 'Calm', 'Lull', 'Soothe'],
    'clr-shd-shm/tank/carry': ['Word of Health', 'Walking Sleep', 'Malaisement', 'Mana Convert', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV'],
    'clr-shd-shm/tank/worn': ['Unrighteous Bash', 'Heritage of Mistmoore', 'See Invisible'],
    'clr-shd-shm/tank/proc': ['Banish Summoned', 'Banish Undead', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Cleanse'],
    'clr-shd-shm/melee/focus': ['Spell Haste II', 'Improved Damage III', 'Extended Range II', 'Improved Healing III', 'Reagent Conservation III', 'Mana Preservation II', 'Extended Enhancement II'],
    'clr-shd-shm/melee/click': ['Superior Healing', 'Spirit Tap', 'Alacrity', 'Restore Sight', 'Calm', 'Illusion: Earth Elemental'],
    'clr-shd-shm/melee/carry': ['Walking Sleep', 'Malaisement', 'Word of Health', 'Mana Convert', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV'],
    'clr-shd-shm/melee/worn': ['Unrighteous Bash', 'Heritage of Mistmoore', 'See Invisible'],
    'clr-shd-shm/melee/proc': ['Banish Summoned', 'Banish Undead', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Cleanse'],
    'clr-shd-shm/caster/focus': ['Spell Haste II', 'Mana Preservation II', 'Burning Affliction II', 'Improved Healing III', 'Extended Range II', 'Reagent Conservation III', 'Extended Enhancement II'],
    'clr-shd-shm/caster/click': ['Superior Healing', 'Restore Sight', 'Spirit Tap', 'Calm', 'Lull', 'Soothe'],
    'clr-shd-shm/caster/carry': ['Mana Convert', 'Malaisement', 'Word of Health', 'Walking Sleep', 'Illusion: Tree', 'Fear', 'Companion Spirit', 'Healing'],
    'clr-shd-shm/caster/worn': ['Heritage of Mistmoore', 'See Invisible', 'Enduring Breath'],
    'clr-shd-shm/caster/proc': ['Banish Summoned', 'Banish Undead', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Cleanse'],
}

# (regenerated for the builds: the six builds changed the templates the click and proc scores read, and the Balanced build is gone; the lists are those of this port, as above. Part E2 had regenerated
# eight of them from the code under test; they are the builds' lists again, and what the lists must be is stated and derived by hand below (F2, G5): the solver's value a minute of a proc, whatever its kind, the
# cap of the lasting part of a damage proc, and the scale of a full proc measured over the same value. The six proc lists are those of that derivation: a proc that the table gives a share of a full proc
# (Haste, 0.6) ranks above a damage proc that it values lower (Flame Shock, 0.43), a heal that the trio's own spells cover is worth almost nothing (Cleanse, 0.0075) and leaves the lists, and a proc
# that the rule does not count (Ykesha: a mark) scores nothing)
NOW = {
    'pal-mnk-ber/tank/focus': ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Extended Enhancement II', 'Reagent Conservation II', 'Mana Preservation II'],
    'pal-mnk-ber/tank/click': ['Alacrity', 'Pillage Enchantment', 'Superior Healing', 'Spirit of Wolf', 'Spirit Tap', 'Raging Strength'],
    'pal-mnk-ber/tank/carry': ['Walking Sleep', 'Bramblecoat', 'Divine Aura', 'Levitate', 'Rune I', 'Rune IV', 'Healing', 'Breath of the Dead'],
    'pal-mnk-ber/tank/worn': ['Unrighteous Bash', 'Virtuous Bash', 'Heritage of Mistmoore'],
    'pal-mnk-ber/tank/proc': ["Oathbreaker's Curse", 'Earthquake', 'Haste', 'Haste', 'Flame Shock', 'Soul Leech'],
    'pal-mnk-ber/melee/focus': ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Extended Enhancement II', 'Reagent Conservation II', 'Mana Preservation II'],
    'pal-mnk-ber/melee/click': ['Alacrity', 'Pillage Enchantment', 'Spirit of Wolf', 'Superior Healing', 'Spirit Tap', 'Raging Strength'],
    'pal-mnk-ber/melee/carry': ['Walking Sleep', 'Levitate', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV', 'Breath of the Dead', 'Enduring Breath'],
    'pal-mnk-ber/melee/worn': ['Unrighteous Bash', 'Virtuous Bash', 'Heritage of Mistmoore'],
    'pal-mnk-ber/melee/proc': ["Oathbreaker's Curse", 'Earthquake', 'Haste', 'Haste', 'Flame Shock', 'Soul Leech'],
    'clr-shd-shm/tank/focus': ['Spell Haste II', 'Improved Damage III', 'Extended Range II', 'Improved Healing III', 'Reagent Conservation II', 'Extended Enhancement II', 'Mana Preservation II'],
    'clr-shd-shm/tank/click': ['Pillage Enchantment', 'Superior Healing', 'Spirit Tap', 'Rune III', 'Restore Sight', 'Calm'],
    'clr-shd-shm/tank/carry': ['Walking Sleep', 'Word of Health', 'Malaisement', 'Mana Convert', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV'],
    'clr-shd-shm/tank/worn': ['Unrighteous Bash', 'Heritage of Mistmoore', 'See Invisible'],
    'clr-shd-shm/tank/proc': ['Heat Blood', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Earthquake', 'Banish Undead'],
    'clr-shd-shm/shield/focus': ['Spell Haste II', 'Burning Affliction II', 'Improved Healing III', 'Extended Range II', 'Reagent Conservation II', 'Extended Enhancement II', 'Mana Preservation II'],
    'clr-shd-shm/shield/click': ['Pillage Enchantment', 'Superior Healing', 'Spirit Tap', 'Rune III', 'Restore Sight', 'Calm'],
    'clr-shd-shm/shield/carry': ['Walking Sleep', 'Word of Health', 'Malaisement', 'Mana Convert', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV'],
    'clr-shd-shm/shield/worn': ['Unrighteous Bash', 'Heritage of Mistmoore', 'See Invisible'],
    'clr-shd-shm/shield/proc': ['Heat Blood', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Earthquake', 'Banish Undead'],
    'clr-shd-shm/melee/focus': ['Spell Haste II', 'Improved Damage III', 'Extended Range II', 'Improved Healing III', 'Reagent Conservation II', 'Extended Enhancement II', 'Mana Preservation II'],
    'clr-shd-shm/melee/click': ['Pillage Enchantment', 'Superior Healing', 'Spirit Tap', 'Rune III', 'Alacrity', 'Restore Sight'],
    'clr-shd-shm/melee/carry': ['Walking Sleep', 'Malaisement', 'Word of Health', 'Mana Convert', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV'],
    'clr-shd-shm/melee/worn': ['Unrighteous Bash', 'Heritage of Mistmoore', 'See Invisible'],
    'clr-shd-shm/melee/proc': ['Heat Blood', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Earthquake', 'Banish Undead'],
    'clr-shd-shm/caster/focus': ['Spell Haste II', 'Mana Preservation II', 'Burning Affliction II', 'Improved Healing III', 'Extended Range II', 'Reagent Conservation II', 'Extended Enhancement II'],
    'clr-shd-shm/caster/click': ['Pillage Enchantment', 'Superior Healing', 'Restore Sight', 'Spirit Tap', 'Calm', 'Lull'],
    'clr-shd-shm/caster/carry': ['Mana Convert', 'Walking Sleep', 'Malaisement', 'Word of Health', 'Illusion: Tree', 'Fear', 'Companion Spirit', 'Healing'],
    'clr-shd-shm/caster/worn': ['Heritage of Mistmoore', 'See Invisible', 'Enduring Breath'],
    'clr-shd-shm/caster/proc': ['Heat Blood', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Earthquake', 'Banish Undead'],
}


REASON = {
    "focus": "partial credit above a focus's maximum level",
    "click": "the dispel constant, and the click scale measured against effects that can be offered",
    "carry": "the click scale measured against effects that can be offered",
    "worn": "the click scale measured against effects that can be offered",
    "proc": "Dismiss and Banish work on some targets only, and the proc scale measured against what a proc score is",
}


@pytest.mark.parametrize("key", sorted(NOW))
def test_the_lists_of_the_example_trios_are_the_ones_the_fixes_give(built, key):
    slug, role, kind = key.split("/")
    assert [o["name"] for o in lists(built, slug, role)[kind]] == NOW[key]  # (the order is the one that is held: the four foci that are close are derived by hand in G6 below)


# ---- F2, G5: what a proc is worth in the lists, derived by hand -----------------------------------------------------------------------------------------------------------
#
# The solver's table values a proc record with ONE function (effects.value.effect_value) and the lists score a record with the same value over the value of a full proc (a proc a minute of the scale
# of a full proc), at most 1. Here the value of each named record is worked out from the rules and from the numbers of the client's spell, in the comments, and written as a literal: the test compares
# the code with the literal, not with itself. The rules: a proc lands PPM = (200 / 170 + 0.5) = 57/34 times a minute at the reference DEX (times 1 + Rate/100 for a record that lists a Rate line)
# and 17/20 of its damage lands; one proc a minute at no Rate line is 57/34 x 17/20 = 57/40 = 1.425 times its size. A Dismiss or a Banish (target 9, 10 or 11) does 7/20 of its damage. The lasting part
# of a damage proc is held to one copy up at a time: its damage x 17/20 x 60 s / (6 s x ticks). A heal, a haste and the like are a share of a full proc (rule effects.proc_value: heal 0.6, haste 0.6;
# 0.05 for a kind the rule does not list), cut to 0.15 when a class of the trio has a spell of its own of that kind and to 0.1 for a haste proc when a class of the trio gives haste (a Shaman).
# A record that may be one of several spells of the client (marked ambiguous) is worth the smallest of them; a record marked with anything the rule does not count (inferred, description) is worth 0.

PPM = Fraction(57, 34)
LANDING = Fraction(17, 20)
PER_PROC = PPM * LANDING  # 57/40: what one proc a minute is worth for each point of its size
FULL_PROC = Fraction(731, 2)  # a full proc a minute: Heat Blood, 258 over 6 ticks (36 s): 258 x 17/20 x 60 / 36 = 365.5, under the 258 x 57/40 = 367.65 it would do at the rate
SCALE = FULL_PROC / PER_PROC  # 14620/57, 256.49: the size of a full proc (90th percentile of the procs of the table that do damage)

#: (name, cast level) -> value a minute for PAL/MNK/BER (and for CLR/SHD/SHM where it differs: HASTE_OF_A_TRIO_THAT_HASTENS), by hand
HAND = {
    # Heat Blood, 258 over 6 ticks: the cap, 258 x 17/20 x 10 / 6 = 365.5 (the rate alone would give 367.65): this is the full proc
    ("Heat Blood", None): Fraction(731, 2),
    # Oathbreaker's Curse, 720 over 9 ticks (54 s): the cap, 720 x 17/20 x 10 / 9 = 680 (the rate alone: 1,026); more than a full proc
    ("Oathbreaker's Curse", None): Fraction(680),
    # Scourge, 58 at once and 1,056 over 12 ticks (72 s), the smaller of its two spells (the other has 280 and 2,880): 58 x 57/40 = 82.65 and the cap 1,056 x 17/20 x 10 / 12 = 748: 830.65
    ("Scourge", 30): Fraction(16613, 20),
    # Winter's Roar, 230 at once (the other of its spells does 243), a Rate line of +64: 230 x (57/34 x 1.64) x 17/20 = 537.51
    ("Winter's Roar", 30): Fraction(53751, 100),
    # Earthquake, a hit of 246 (its other spell is a damage over time of 4,500 with no end: worth far more): 246 x 57/40 = 350.55
    ("Earthquake", 45): Fraction(7011, 20),
    # Flame Shock: the smaller of 175 and 110 is 110: 110 x 57/40 = 156.75
    ("Flame Shock", 45): Fraction(627, 4),
    # Chaos Flux: the smaller of 175 and 150 is 150: 150 x 57/40 = 213.75
    ("Chaos Flux", 46): Fraction(855, 4),
    # Spirit Strike, a Rate line of +50: the smallest of its four spells (78, 50, 50, 500) is 50: 50 x (57/34 x 1.5) x 17/20 = 106.875
    ("Spirit Strike", 35): Fraction(855, 8),
    # Soul Leech, a lifetap of 75: 75 x 57/40 = 106.875
    ("Soul Leech", 45): Fraction(855, 8),
    # Ykesha is marked description, which the rule does not count: 0 (the lists took its 75 as a damage proc of 0.292 of a full one)
    ("Ykesha", 37): Fraction(0),
    # Banish Summoned, 535 on a Banish (target 11): 535 x 57/40 x 7/20 = 266.83125
    ("Banish Summoned", 45): Fraction(42693, 160),
    # Banish Undead (cast level 40), 430 on a Dismiss (target 10), a Rate line of +54: 430 x (57/34 x 1.54) x 17/20 x 7/20 = 330.27225
    ("Banish Undead", 40): Fraction(1321089, 4000),
    # Cleanse may be a heal of 5 (0.6 x 0.15 of a full proc) or a spell of a kind the rule does not list (0.05, cut to 0.15 by the spells of the Paladin or the Cleric): the smaller, 0.0075 of 365.5
    ("Cleanse", None): Fraction(2193, 800),
    # Haste (cast 25 and 30), a share of 0.6 of a full proc: 0.6 x 365.5 = 219.3 (21.93 for a trio with a Shaman, who gives haste: 0.1 of it)
    ("Haste", 25): Fraction(2193, 10),
    ("Haste", 30): Fraction(2193, 10),
}
HASTE_OF_A_TRIO_THAT_HASTENS = Fraction(2193, 100)


def record_of(built, name, cast):
    (found,) = [e for e in built.effects if dn.kind_of(e) == "proc" and e["name"] == name and e.get("cast_level") == cast]
    return found


def test_the_scale_of_a_full_proc_is_the_size_of_heat_blood_and_exact(built):
    assert built.ctx.proc_scale == SCALE == Fraction(14620, 57) and isinstance(built.ctx.proc_scale, Fraction)  # (a float would be one ulp from the proc at the percentile, and the lists compare with it)
    assert float(SCALE) == pytest.approx(256.49, abs=0.005)
    # the procs of the table that do damage: the 90th percentile of their sizes, the size being the value a minute over 57/40 (a value of 0 is no proc of the table and measures nothing)
    from trioforge.effects.value import damage_record_value

    book = sp.SpellBook.load()
    sizes = sorted(
        size
        for size in (damage_record_value(e, book, J) / PER_PROC for e in built.effects if dn.kind_of(e) == "proc" and e.get("category") in ("damage", "dot", "lifetap") and e.get("magnitude") and layer.offerable(e, J))
        if size > 0
    )
    assert sizes[int(0.9 * (len(sizes) - 1))] == SCALE
    assert sum(1 for size in sizes if size > SCALE) == 6  # six procs are larger than a full one, the four of the lists of clr-shd-shm among them


def test_the_scale_is_measured_over_the_damage_spells_of_a_record_and_the_table_over_all_of_them_and_no_real_record_differs(built):
    """H8: for a record that may be one of several spells the scale is measured over the smallest of the DAMAGE spells it may be (it cannot be read from a spell that is valued by the scale), and the table takes
    the smallest over all the spells it may be. They differ only for a damage record that may also be a spell of another kind that is worth less to a trio; no record of the catalog does that, for any trio."""
    import itertools

    from trioforge.effects import score
    from trioforge.effects.value import damage_record_value

    book = sp.SpellBook.load()
    ambiguous = [e for e in built.effects if dn.kind_of(e) == "proc" and e.get("category") in ("damage", "dot", "lifetap") and "ambiguous" in (e.get("unverified") or ())]
    assert len(ambiguous) >= 5
    for trio in itertools.combinations(CLASS_CODES, 3):
        for e in ambiguous:
            assert score.effect_value(e, built.ctx, book, J, trio) == damage_record_value(e, book, J), (e["name"], trio)


def test_the_scale_is_exact_end_to_end_so_that_heat_blood_is_a_full_proc_to_the_last_digit(built):
    """(G9) Heat Blood is the proc at the percentile: its value over a full proc is exactly 1 only while the scale is the exact number the percentile picked. Read back through a float it is another number
    (the scale of 14620/57 is 256.4912280701754...), which would put Heat Blood a hair over or under the three procs that score 1.0 and reorder the four that are tied. The scale is kept as the Fraction
    that was picked, from where it is measured to every place that reads it, and is written to no file."""
    from trioforge.effects import score
    from trioforge.effects.value import fr

    book = sp.SpellBook.load()
    heat = record_of(built, "Heat Blood", None)
    value = score.effect_value(heat, built.ctx, book, J, ("SHD",))
    assert isinstance(built.ctx.proc_scale, Fraction) and value / (PER_PROC * fr(built.ctx.proc_scale)) == 1
    assert value / (PER_PROC * fr(float(built.ctx.proc_scale))) != 1  # (the float read back is not the scale)
    clr = lists(built, "clr-shd-shm", "tank")["proc"]
    assert [o["name"] for o in clr[:4]] == ["Heat Blood", "Oathbreaker's Curse", "Scourge", "Winter's Roar"] and len({o["score"] for o in clr[:4]}) == 1


@pytest.mark.parametrize(("name", "cast"), sorted(HAND, key=lambda key: (key[0], key[1] or 0)))
def test_the_table_values_the_named_records_as_they_are_worked_out_by_hand(built, name, cast):
    from trioforge.effects import score

    book = sp.SpellBook.load()
    effect = record_of(built, name, cast)
    assert score.effect_value(effect, built.ctx, book, J, ("PAL", "MNK", "BER")) == HAND[(name, cast)]
    assert score.effect_value(effect, built.ctx, book, J, ("CLR", "SHD", "SHM")) == (HASTE_OF_A_TRIO_THAT_HASTENS if name == "Haste" else HAND[(name, cast)])


def test_every_proc_record_is_scored_in_the_lists_by_the_value_the_table_gives_it_over_a_full_proc(built):
    """One function for every record, damage or not, with the mark rule, the candidates, the restricted share and the haste cut in it: nothing is skipped (this is the consistency of the two uses; the
    values themselves are held to the hand derivation above)."""
    from trioforge.effects import score

    book = sp.SpellBook.load()
    checked = 0
    for trio in (("PAL", "MNK", "BER"), ("CLR", "SHD", "SHM"), ("WAR", "SHM", "ENC"), ("RNG", "SHD", "WIZ")):
        frac = max(J.score_shape["proc_melee_floor"], sum(c in layer.MELEE_CLASSES for c in trio) / len(trio))
        for effect in built.effects:
            if dn.kind_of(effect) != "proc":
                continue
            ratio = score.effect_value(effect, built.ctx, book, J, trio) / FULL_PROC
            assert layer._proc_score(effect, 0.5, list(trio), built.ctx) == pytest.approx(0.5 * frac * min(1.0, float(ratio)), abs=1e-12), (effect["name"], effect.get("cast_level"), trio)
            checked += 1
    assert checked > 500


def test_a_record_that_the_rule_does_not_count_scores_nothing_in_the_lists_and_is_not_listed(built):
    ykesha = record_of(built, "Ykesha", 37)
    assert layer._proc_score(ykesha, 1.0, ["PAL", "MNK", "BER"], built.ctx) == 0.0
    assert "Ykesha" not in {o["name"] for slug in ("pal-mnk-ber", "clr-shd-shm") for role in ("tank", "melee") for o in lists(built, slug, role, top=False)["proc"]}


def offered_names(built, trio):
    """The proc records that a copy exists of for the trio, by their donors (a copy that can be worn, that a class of the trio can use, within the cap): data, not a score."""
    return {
        (e["name"], e.get("cast_level"))
        for e in built.effects
        if dn.kind_of(e) == "proc"
        and any(d["eligible"] and dn.usable_by(d, list(trio)) and not (d["req_level"] and d["req_level"] > J.cap) for d in e["items"])
    }


@pytest.mark.parametrize(("trio", "sixth"), [(("PAL", "MNK", "BER"), Fraction(2924, 10000)), (("CLR", "SHD", "SHM"), Fraction(9036, 10000))])
def test_no_proc_that_the_hand_derivation_leaves_out_could_be_in_the_top_of_a_list(built, trio, sixth):
    """The lists below hold six procs each. A record that is offered to the trio and is worth as much as the sixth of them (0.2924 of a full proc for PAL/MNK/BER: Soul Leech and Spirit Strike tie there;
    0.9036 for CLR/SHD/SHM: Banish Undead) must be one that is worked out by hand above: nothing the derivation has not seen can be in a list or push one out."""
    from trioforge.effects import score

    book = sp.SpellBook.load()
    unseen = []
    for name, cast in sorted(offered_names(built, trio), key=lambda key: (key[0], key[1] or 0)):
        ratio = score.effect_value(record_of(built, name, cast), built.ctx, book, J, trio) / FULL_PROC
        if ratio >= sixth and (name, cast) not in HAND:
            unseen.append((name, cast, float(ratio)))
    assert unseen == [], f"records worth a place in a list that are not derived by hand above: {unseen}"


def test_the_first_procs_of_the_example_trios_are_the_ones_the_hand_valuation_puts_first(built):
    # pal-mnk-ber: Oathbreaker's Curse (680 a minute, more than a full proc, 1.0), Earthquake (350.55 / 365.5 = 0.959), Haste twice (0.6: a share of a full proc, and no Shaman to cut it), Flame Shock
    # (156.75 / 365.5 = 0.429), and the sixth place to Soul Leech (106.875 / 365.5 = 0.292), which Spirit Strike (also 106.875) ties with and loses by its effect id. Cleanse (0.0075) and Ykesha (nothing)
    # are not in the list; Chaos Flux and Banish Summoned are worth 0.58 and 0.73 and have no donor that this trio can wear
    for role in ("tank", "melee"):
        got = lists(built, "pal-mnk-ber", role)["proc"]
        assert [o["name"] for o in got] == ["Oathbreaker's Curse", "Earthquake", "Haste", "Haste", "Flame Shock", "Soul Leech"]
        ratios = [min(1.0, float(HAND[key] / FULL_PROC)) for key in (("Oathbreaker's Curse", None), ("Earthquake", 45), ("Haste", 25), ("Haste", 30), ("Flame Shock", 45), ("Soul Leech", 45))]
        assert [o["score"] / got[0]["score"] for o in got] == pytest.approx(ratios, abs=0.002)  # (the first is 1.0: the cap)
    assert {"Chaos Flux", "Banish Summoned"}.isdisjoint(offered for offered, _ in offered_names(built, ("PAL", "MNK", "BER")))
    assert HAND[("Soul Leech", 45)] == HAND[("Spirit Strike", 35)]  # (the tie of the sixth place)
    tied = [e["id"] for e in (record_of(built, "Soul Leech", 45), record_of(built, "Spirit Strike", 35))]
    assert tied == sorted(tied)  # (the smaller id first: Soul Leech)
    # clr-shd-shm: four procs of the most a proc scores (Heat Blood is exactly a full proc, Oathbreaker's Curse, Scourge and Winter's Roar are over it), in the order of their ids; then Earthquake (0.959) and
    # Banish Undead (330.27 / 365.5 = 0.904); the Shaman's haste is worth 0.06 of a full proc and Cleanse 0.0075, so neither is in the list
    for role in ("tank", "shield", "melee", "caster"):
        clr = lists(built, "clr-shd-shm", role)["proc"]
        assert [o["name"] for o in clr] == ["Heat Blood", "Oathbreaker's Curse", "Scourge", "Winter's Roar", "Earthquake", "Banish Undead"]
        assert [o["effect"] for o in clr[:4]] == sorted(o["effect"] for o in clr[:4])  # (equal scores: by id)
        assert len({o["score"] for o in clr[:4]}) == 1
        ratios = [min(1.0, float(HAND[key] / FULL_PROC)) for key in (("Earthquake", 45), ("Banish Undead", 40))]
        if role in ("tank", "melee"):  # (a score is kept to three decimals: for the Shield caster and the Caster, where a full proc scores 0.025, that is too coarse to say 0.90 from 0.92)
            assert [o["score"] / clr[0]["score"] for o in clr[4:]] == pytest.approx(ratios, abs=0.002)


def test_a_poison_of_a_quarter_of_an_hour_does_not_outrank_a_proc_that_does_more_a_minute(built):
    # Disease: 10 at once and 300 over 150 ticks (a quarter of an hour): 10 x 57/40 = 14.25 and the cap 300 x 17/20 x 10 / 150 = 17: 31.25 a minute, 0.0855 of a full proc; Strong Poison (30 at once and 280 over
    # 20 ticks, two minutes): 30 x 57/40 = 42.75 and 280 x 17/20 x 10 / 20 = 119: 161.75, 0.4425. Flame Shock is worth 156.75 to 0.43; the lists once counted the 310 whole of Disease, more than Flame Shock's 175
    disease, strong, flame = Fraction(125, 4), Fraction(647, 4), HAND[("Flame Shock", 45)]
    assert disease == 10 * PER_PROC + 300 * LANDING * 10 / 150 and strong == 30 * PER_PROC + 280 * LANDING * 10 / 20
    assert disease < strong and disease / FULL_PROC == pytest.approx(0.0855, abs=0.0005) and strong / FULL_PROC == pytest.approx(0.4425, abs=0.0005)
    from trioforge.effects import score

    book = sp.SpellBook.load()
    for name, want in (("Disease", disease), ("Strong Poison", strong)):
        (effect,) = [e for e in built.effects if dn.kind_of(e) == "proc" and e["name"] == name and e["category"] == "dot" and e.get("lasting")]
        assert score.effect_value(effect, built.ctx, book, J, ("PAL", "MNK", "BER")) == want
    for slug, role in (("pal-mnk-ber", "tank"), ("pal-mnk-ber", "melee"), ("clr-shd-shm", "tank"), ("clr-shd-shm", "shield"), ("clr-shd-shm", "melee"), ("clr-shd-shm", "caster")):
        assert not {"Disease", "Strong Poison"} & {o["name"] for o in lists(built, slug, role)["proc"]}, (slug, role)
        names = [o["name"] for o in lists(built, slug, role, top=False)["proc"]]
        for rival in ("Flame Shock", "Strong Poison"):  # (the procs that a trio's classes can wear: not every trio has both)
            if "Disease" in names and rival in names:
                assert names.index("Disease") > names.index(rival), (slug, role, rival)
    assert flame > disease


# ---- G6, H4: the order of the close foci of clr-shd-shm, derived by hand ----------------------------------------------------------------------------------------------
#
# In the lists of the Shield caster and the Caster of clr-shd-shm four foci are close: Improved Healing III (10.5 percent) and Burning Affliction II (10.5), Mana Preservation II (5.5) and Extended
# Enhancement II (15). The score of a focus in a build is
#
#     spell relevance x sum over the classes c of the trio ( weight of c x value of the kind of focus x magnitude x share of c x mass of c [x mana weight of the build, for Mana Preservation] ) / sum of the weights
#
# where the share of a class is, over the kinds of spell the class has among its late spells (level 30 to the cap), the sum of (weight of the kind x the average over its spells of how much of the
# focus each gets) over the sum of the weights of the kinds (a spell above the focus's maximum level, 44, gets 5 percent less for each level above it; a spell the focus does not apply to gets 0).
# The rules give: the value of the kinds of focus 1, 1, 0.6 and 0.15; the weight of a class in the Shield caster and the Caster 1 for Cleric and Shaman and 0.25 for the Shadow Knight (off_role_class);
# the mana weight of a build is its template's over the Caster's (0.3 / 4 = 0.075 for the Shield caster, 1 for the Caster) and the spell relevance 0.3 + 0.7 x that (0.3525 and 1); every class here casts
# enough to have a mass of 1. The table is what the spell book says of the late spells of the three classes, by kind: (weight of the kind, spells of the kind, what each focus touches of them: the sum
# of the shares each spell gets). The spells' kinds are those the rules give (the test checks the table against the book, and the kind of every spell that has both a one-time and a lasting part against the
# rule written out again from its effect rows below).
#
# The kind of a mixed spell (H4). A spell with a one-time part (SPA 79, or the whole of an instant spell) and a lasting part (SPA 0 or 100 for every tick of its duration) is of the kind of the LARGER
# part: the one-time total against the lasting total, a tie to the one-time kind (a permanent spell has no end to its total: it is over time). Two Cleric heals and four Ranger spells are mixed with the
# one-time part larger (spell, level, effect rows: the number of SPA 79 and of SPA 100 or 0 for the one tick):
#     74001 (Cleric 8): 50 + 20 over 1 tick -> heal 70        74002 (14): 140 + 55 -> heal 195        74003 (24): 265 + 110 -> heal 375
#     74004 (Cleric 34): 310 + 165 over 1 tick -> heal 475 (65 percent direct)         74005 (Cleric 43): 640 + 260 -> heal 900 (71 percent direct)
#     (and, for the Ranger, 3564 and 3565, 74041 and 74042: a hit of 155, 102, 58 and 210 with 78, 51, 29 and 105 over a tick: damage, not damage over time.)
# E2 had made all nine over time (heal over time, damage over time), whatever the size of the lasting part. The Cleric's five spells are plain heals again; of them only 74004 and 74005 are late spells (level
# 30 and over), so the Cleric's kind of heal has the four instant heals it had and these two: 6 late spells, of which Improved Healing III touches 4 (it applies to a heal that is over at once, and the two
# that last a tick get nothing from it) and Mana Preservation all 6; and the kind of heal over time has the 1 spell that is mostly over time, of which Extended Enhancement touches the 1 (four ticks or more:
# the two heals of a tick get nothing from it either, and are in the other kind). So the Cleric's share of Improved Healing III is 4 of 6 of its kind (0.164) and the Shield caster's score of it 0.628, under
# Burning Affliction's 0.756; the Cleric's share of Extended Enhancement is 1 of 1 of its kind (0.162) and the Shield caster's score 0.107, over Mana Preservation's 0.084. These are the orders the lists
# had before E2.

FOCI = {"Improved Healing III": "heal", "Burning Affliction II": "dot", "Mana Preservation II": "mana", "Extended Enhancement II": "ext"}
FOCUS_VALUE = {"heal": Fraction(1), "dot": Fraction(1), "mana": Fraction(3, 5), "ext": Fraction(3, 20)}
MAGNITUDE = {"heal": Fraction(21, 2), "dot": Fraction(21, 2), "mana": Fraction(11, 2), "ext": Fraction(15)}
CLASS_WEIGHT = {"CLR": Fraction(1), "SHD": Fraction(1, 4), "SHM": Fraction(1)}
MANA_WEIGHT = {"shield": Fraction(3, 40), "caster": Fraction(1)}
#: kind -> (weight of the kind, late spells of the kind, {focus: sum of the shares the spells get}); the kinds of weight 0 (cures, resurrections, items, ...) count for nothing and are left out
KINDS = {
    "CLR": {
        "buff_resist": (Fraction(3, 100), 5, {"heal": 0, "dot": 0, "mana": Fraction(5), "ext": Fraction(5)}),
        "buff_stats": (Fraction(3, 100), 12, {"heal": 0, "dot": 0, "mana": Fraction(233, 20), "ext": Fraction(233, 20)}),
        "crowd_control": (Fraction(2, 5), 4, {"heal": 0, "dot": 0, "mana": Fraction(39, 10), "ext": 0}),
        "damage": (Fraction(1), 12, {"heal": 0, "dot": 0, "mana": Fraction(23, 2), "ext": 0}),
        "dot": (Fraction(1), 1, {"heal": 0, "dot": Fraction(1), "mana": Fraction(1), "ext": 0}),
        # four instant heals (Improved Healing 4, Mana Preservation 3.9: a spell of level 45 or more gets 5 percent less for each level above 44) and the two fast heals of one tick, 74004 and 74005 (levels 34
        # and 43: Improved Healing 0, Mana Preservation 1 + 1, Extended Enhancement 0)
        "heal": (Fraction(1), 6, {"heal": Fraction(4), "dot": 0, "mana": Fraction(39, 10) + 2, "ext": 0}),
        "heal_over_time": (Fraction(3, 5), 1, {"heal": 0, "dot": 0, "mana": Fraction(1), "ext": Fraction(1)}),
    },
    "SHD": {
        "buff_protection": (Fraction(3, 100), 1, {"heal": 0, "dot": 0, "mana": Fraction(1), "ext": Fraction(1)}),
        "buff_resist": (Fraction(3, 100), 1, {"heal": 0, "dot": 0, "mana": Fraction(1), "ext": Fraction(1)}),
        "crowd_control": (Fraction(2, 5), 1, {"heal": 0, "dot": 0, "mana": Fraction(1), "ext": 0}),
        "damage": (Fraction(1), 7, {"heal": 0, "dot": 0, "mana": Fraction(121, 20), "ext": 0}),
        "debuff": (Fraction(3, 10), 3, {"heal": 0, "dot": 0, "mana": Fraction(27, 10), "ext": 0}),
        "dot": (Fraction(1), 5, {"heal": 0, "dot": Fraction(4), "mana": Fraction(5), "ext": Fraction(1)}),
        "lifetap": (Fraction(1), 4, {"heal": 0, "dot": 0, "mana": Fraction(18, 5), "ext": 0}),
        "summon_pet": (Fraction(1, 2), 3, {"heal": 0, "dot": 0, "mana": Fraction(29, 10), "ext": 0}),
    },
    "SHM": {
        "buff_resist": (Fraction(3, 100), 4, {"heal": 0, "dot": 0, "mana": Fraction(37, 10), "ext": Fraction(37, 10)}),
        "buff_stats": (Fraction(3, 100), 17, {"heal": 0, "dot": 0, "mana": Fraction(163, 10), "ext": Fraction(163, 10)}),
        "crowd_control": (Fraction(2, 5), 3, {"heal": 0, "dot": 0, "mana": Fraction(3), "ext": 0}),
        "damage": (Fraction(1), 6, {"heal": 0, "dot": 0, "mana": Fraction(117, 20), "ext": 0}),
        "debuff": (Fraction(3, 10), 4, {"heal": 0, "dot": 0, "mana": Fraction(19, 5), "ext": 0}),
        "dot": (Fraction(1), 6, {"heal": 0, "dot": Fraction(11, 2), "mana": Fraction(11, 2), "ext": 0}),
        "haste": (Fraction(1, 20), 2, {"heal": 0, "dot": 0, "mana": Fraction(17, 10), "ext": Fraction(17, 10)}),
        "heal": (Fraction(1), 3, {"heal": Fraction(3), "dot": 0, "mana": Fraction(53, 20), "ext": 0}),
        "heal_over_time": (Fraction(3, 5), 4, {"heal": 0, "dot": 0, "mana": Fraction(4), "ext": Fraction(4)}),
        "mana": (Fraction(1, 5), 1, {"heal": Fraction(1), "dot": 0, "mana": Fraction(1), "ext": 0}),
        "slow": (Fraction(2, 5), 1, {"heal": 0, "dot": 0, "mana": Fraction(1), "ext": 0}),
        "summon_pet": (Fraction(1, 2), 4, {"heal": 0, "dot": 0, "mana": Fraction(79, 20), "ext": 0}),
    },
}


def hand_share(cls, focus):
    kinds = KINDS[cls].values()
    return sum(weight * Fraction(touched[focus]) / count for weight, count, touched in kinds) / sum(weight for weight, _, _ in kinds)


def hand_score(role, focus):
    mana = MANA_WEIGHT[role]
    spell = Fraction(3, 10) + Fraction(7, 10) * mana
    total = sum(CLASS_WEIGHT.values())
    return spell * sum(CLASS_WEIGHT[c] * FOCUS_VALUE[focus] * MAGNITUDE[focus] * hand_share(c, focus) * (mana if focus == "mana" else 1) for c in CLASS_WEIGHT) / total


#: what the hand derivation comes to, to five decimals: the Cleric's share of Improved Healing III is (1 x 4/6) / 4.06 = 0.1642, of Burning Affliction II 1 / 4.06 = 0.2463, the Shaman's (3/3 x 1 + 1/1 x 0.2) / 5.51 =
#: 0.2178 and 5.5/6 / 5.51 = 0.1664, the Shadow Knight's 0 and (4/5) / 4.26 = 0.1878; for the Shield caster Improved Healing III is 0.3525 x 10.5 x (0.1642 + 0.25 x 0 + 0.2178) / 2.25 = 0.6284 and Burning Affliction II
#: 0.3525 x 10.5 x (0.2463 + 0.25 x 0.1878 + 0.1664) / 2.25 = 0.7561 (the Cleric's Extended Enhancement share is (0.6 x 1/1 + 0.03 x 1 + 0.03 x 233/240) / 4.06 = 0.1623: 0.1073 for the Shield caster
# over Mana Preservation's 0.0841); for the Caster Mana Preservation II is 3.1822, Burning Affliction II 2.1449, Improved Healing III 1.7826 and Extended Enhancement II 0.3045
HAND_SCORES = {
    "shield": {"heal": 0.62837, "dot": 0.75607, "mana": 0.08413, "ext": 0.10732},
    "caster": {"heal": 1.78262, "dot": 2.14488, "mana": 3.18222, "ext": 0.30447},
}


@pytest.mark.parametrize("role", ["shield", "caster"])
@pytest.mark.parametrize("focus", sorted(FOCI.values()))
def test_the_hand_derivation_of_the_four_close_foci_comes_to_the_numbers_written_here(role, focus):
    assert float(hand_score(role, focus)) == pytest.approx(HAND_SCORES[role][focus], abs=5e-6)


#: the spells of one one-time part and one lasting part that the rule of H4 reads: id -> (the class and its level, the number of SPA 79, the number of SPA 100 or 0 for every tick, the ticks)
MIXED_ROWS = {
    74001: ("CLR", 8, 50, 20, 1), 74002: ("CLR", 14, 140, 55, 1), 74003: ("CLR", 24, 265, 110, 1), 74004: ("CLR", 34, 310, 165, 1), 74005: ("CLR", 43, 640, 260, 1),
    3564: ("RNG", 36, 155, 78, 1), 3565: ("RNG", 26, 102, 51, 1), 74041: ("RNG", 15, 58, 29, 1), 74042: ("RNG", 46, 210, 105, 1),
}


def kind_by_the_rule(spell):
    """The kind of a spell that has both a one-time part (SPA 79) and a lasting part (SPA 0 or 100 for each tick of its duration), written out again from its effect rows: the larger part, a tie to the one-time
    kind; None for a spell that is not of that shape."""
    once = sum(abs(e["value"]) for e in spell["effects"] if e["spa"] == 79)
    each_tick = sum(abs(e["value"]) for e in spell["effects"] if e["spa"] in (0, 100))
    if not (once and each_tick and spell["duration_ticks"]) or spell["target"] == 13:  # (a lifetap is a lifetap whatever its parts)
        return None
    heal = spell["beneficial"] in (1, 2)
    if spell["permanent"] or each_tick * spell["duration_ticks"] > once:
        return "heal_over_time" if heal else "dot"
    return "heal" if heal else "damage"


def test_the_effect_rows_of_the_mixed_spells_are_the_ones_the_rule_is_read_from(built):
    book = sp.SpellBook.load()
    by_id = {s["id"]: s for s in book.class_spells()}
    for sid, (cls, level, once, each_tick, ticks) in MIXED_ROWS.items():
        spell = by_id[sid]
        assert (spell["levels"], spell["duration_ticks"]) == ({cls: level}, ticks)
        assert sum(abs(e["value"]) for e in spell["effects"] if e["spa"] == 79) == once and sum(abs(e["value"]) for e in spell["effects"] if e["spa"] in (0, 100)) == each_tick
        assert kind_by_the_rule(spell) == ("heal" if cls == "CLR" else "damage")  # (the one-time part is the larger of the two)
        assert sp.classify_spell(spell, J)["category"] == kind_by_the_rule(spell)
        assert once > each_tick * ticks
    # the two of them that are late spells of the Cleric (level 30 and over) are 74004 and 74005; Improved Healing applies to a heal that is over at once and Extended Enhancement to four ticks or more
    healing = next(e for e in built.effects if e["name"] == "Improved Healing III")
    extended = next(e for e in built.effects if e["name"] == "Extended Enhancement II")
    for sid in (74004, 74005):
        assert sp.focus_weight(healing["focus"]["limits"], by_id[sid], by_id[sid]["levels"]["CLR"]) == 0
        assert sp.focus_weight(extended["focus"]["limits"], by_id[sid], by_id[sid]["levels"]["CLR"]) == 0


def test_a_context_has_a_book_of_spells_and_cannot_be_made_without_one():
    """H6: ``effect_value`` reads the book for a record that may be one of several spells; a Context with no book would fail on the first such record, so the field has no default."""
    fields = {f.name: f for f in dataclasses.fields(layer.Context)}
    assert "book" in fields and fields["book"].default is dataclasses.MISSING and fields["book"].default_factory is dataclasses.MISSING
    with pytest.raises(TypeError, match="book"):
        layer.Context(J, [], {}, {}, {}, {}, {}, {}, Fraction(1), {}, {})


def test_the_kind_of_a_mixed_spell_changes_no_record_and_so_no_value_of_the_solvers_table(built):
    """H4: the rule moves nine class spells and no effect record of the catalog (probe over the real catalog, 85,680 values of the table over every trio of three classes: none moved). A record that is a mixed
    spell has its lasting part the larger, as every poison of the catalog does, so it is over time in either reading; and a damage kind is valued by its two parts, not by its kind (a hit and a poison are
    one function), so the one place where a kind would decide a value, a heal against a heal over time (0.6 of a full proc against the unlisted share), has no record of the catalog on it."""
    from trioforge.effects import value as value_module

    mixed = [e for e in built.effects if dn.kind_of(e) == "proc" and e.get("once") and e.get("lasting")]
    assert mixed and all(e["lasting"] > e["once"] and e["category"] == "dot" for e in mixed)  # (Strong Poison, Disease, Scourge, ...: 17 records)
    assert not [e for e in built.effects if e["category"] in ("heal", "heal_over_time") and e.get("once") and e.get("lasting")]
    for kind in ("damage", "dot", "lifetap"):
        view = {"category": kind, "once": 500, "lasting": 250, "magnitude": 750, "unit": "hp_total", "duration_ticks": 5, "target": 5}
        assert value_module.damage_value(view, Fraction(57, 34), J) == value_module.damage_value({**view, "category": "damage"}, Fraction(57, 34), J)


def test_the_table_the_derivation_starts_from_is_what_the_spell_book_says(built):
    book = sp.SpellBook.load()
    spells = book.class_spells()
    foci = {FOCI[e["name"]]: e for e in built.effects if e["kind"] == "focus" and e["name"] in FOCI}
    for cls, table in KINDS.items():
        late = [s for s in spells if J.late <= s["levels"].get(cls, 0) <= J.cap]
        kinds = {}
        for spell in late:
            kind = kind_by_the_rule(spell) or sp.classify_spell(spell, J)["category"]  # (a spell of one part has the kind of the rules for it; a mixed one, the kind of the larger part, from its rows)
            kinds.setdefault(kind, []).append(spell)
        assert {kind for kind in kinds if J.weight_of(kind) > 0} == set(table), cls
        for kind, (weight, count, touched) in table.items():
            assert (weight, count) == (Fraction(str(J.weight_of(kind))), len(kinds[kind])), (cls, kind)
            for focus, e in foci.items():
                got = sum(sp.focus_weight(e["focus"]["limits"], s, s["levels"][cls]) for s in kinds[kind])
                assert got == pytest.approx(float(touched[focus]), abs=1e-9), (cls, kind, focus)
    assert sorted(s["id"] for s in spells if J.late <= s["levels"].get("CLR", 0) <= J.cap and kind_by_the_rule(s) == "heal") == [74004, 74005]  # (the two that make the Cleric's kind of heal six)
    for name, key in FOCI.items():
        assert (foci[key]["magnitude"], J.focus_value[foci[key]["focus"]["kind"]]) == (float(MAGNITUDE[key]), float(FOCUS_VALUE[key])), name
    for role in ("shield", "caster"):
        assert {c: Fraction(str(w)) for c, w in layer.role_weights(role, ["CLR", "SHD", "SHM"], J).items()} == CLASS_WEIGHT
        assert layer.role_rel(role, ["CLR", "SHD", "SHM"], J)[1] == pytest.approx(float(MANA_WEIGHT[role]))
    assert all(built.ctx.mass[c] == 1.0 for c in KINDS)


@pytest.mark.parametrize("role", ["shield", "caster"])
def test_the_close_foci_of_the_shield_caster_and_the_caster_come_in_the_order_the_derivation_gives(built, role):
    got = {o["name"]: o["score"] for o in lists(built, "clr-shd-shm", role, top=False)["focus"]}
    by_hand = {name: float(hand_score(role, key)) for name, key in FOCI.items()}
    for name in FOCI:
        assert got[name] == pytest.approx(by_hand[name], abs=1.5e-3), (role, name)  # (the file keeps the shares to four decimals and the list a score to three)
    order = [name for name, _ in sorted(by_hand.items(), key=lambda item: -item[1])]
    assert order == [name for name in (o["name"] for o in lists(built, "clr-shd-shm", role, top=False)["focus"]) if name in FOCI]
    if role == "shield":
        assert order == ["Burning Affliction II", "Improved Healing III", "Extended Enhancement II", "Mana Preservation II"]  # (0.7561 over 0.6284; 0.1073 over 0.0841)
    else:
        assert order == ["Mana Preservation II", "Burning Affliction II", "Improved Healing III", "Extended Enhancement II"]


def test_the_best_heal_of_the_cleric_is_the_whole_of_a_fast_heal_and_that_puts_word_of_health_under_malaisement_in_the_melee_carry_list(built):
    """H4: the two fast heals are plain heals again, so the Cleric's best heal is 74005's whole, 640 + 260 = 900 (it was 801, the largest plain heal, with 900 a heal over time). A click is scored against the
    best spell of its kind that a class of the trio has: Word of Health (a heal of 415, the click scale of heals 671) is worth 1/2 (heal relevance for Melee damage) x 415/671 x (0.3 + 0.7 x 415/900) = 0.1926 where it
    was 0.5 x 415/671 x (0.3 + 0.7 x 415/801) = 0.2049; Malaisement (a debuff of 148 of the scale 220, relevance 0.3, no spell to compare with) is 0.3 x 148/220 = 0.2018: the list had Word of Health over it and has
    it under. (Both are instant casts: the same factor, 1 + 0.25 x 0.32625, on both.)"""
    assert built.ctx.own_best["CLR"]["heal"] == 900 and built.ctx.cat_max["heal"] == 671 and built.ctx.cat_max["debuff"] == 220
    word, malaisement = Fraction(1, 2) * Fraction(415, 671) * (Fraction(3, 10) + Fraction(7, 10) * Fraction(415, 900)), Fraction(3, 10) * Fraction(148, 220)
    assert word < malaisement and Fraction(1, 2) * Fraction(415, 671) * (Fraction(3, 10) + Fraction(7, 10) * Fraction(415, 801)) > malaisement
    scores = {o["name"]: o["score"] for o in lists(built, "clr-shd-shm", "melee", top=False)["carry"]}
    factor = 1 + 0.25 * 0.32625
    assert scores["Word of Health"] == pytest.approx(float(word) * factor, abs=1e-3) and scores["Malaisement"] == pytest.approx(float(malaisement) * factor, abs=1e-3)
    names = [o["name"] for o in lists(built, "clr-shd-shm", "melee")["carry"]]
    assert names.index("Malaisement") < names.index("Word of Health")


#: the lists that differ from the analysis' (the builds the analysis knew: Tank, Melee damage and Caster; the Shield caster and the Caster tank are newer), every one of them because of a
#: fix named in the header or, for the five lists that moved with the builds, because of the mana weight of the templates: a list that differs and is not here is unexplained
DIFFERS_FROM_THE_ANALYSIS = {
    f"{slug}/{role}/{kind}"
    for slug, role, kinds in (
        ("clr-shd-shm", "caster", ("carry", "click", "focus", "proc")),
        ("clr-shd-shm", "melee", ("click", "focus", "proc")),  # (H4: its carry list is the analysis' again: Word of Health under Malaisement)
        ("clr-shd-shm", "tank", ("carry", "click", "focus", "proc")),
        ("pal-mnk-ber", "melee", ("click", "focus", "proc", "worn")),
        ("pal-mnk-ber", "tank", ("click", "focus", "proc", "worn")),
    )
    for kind in kinds
}


def test_the_lists_that_differ_from_the_analysis_are_exactly_the_ones_the_fixes_and_the_templates_explain():
    differing = {key for key in set(NOW) & set(ANALYSIS) if NOW[key] != ANALYSIS[key]}
    assert differing == DIFFERS_FROM_THE_ANALYSIS, sorted(differing ^ DIFFERS_FROM_THE_ANALYSIS)
    assert all(key.split("/")[2] in REASON for key in differing)  # (every kind that differs has its fix named in REASON)


#: the five lists that moved with the builds, as they were with the templates before them
BEFORE_THE_BUILDS = {
    "clr-shd-shm/tank/focus": ['Spell Haste II', 'Improved Damage III', 'Extended Range II', 'Improved Healing III', 'Mana Preservation II', 'Reagent Conservation II', 'Extended Enhancement II'],
    "clr-shd-shm/melee/focus": ['Spell Haste II', 'Improved Damage III', 'Extended Range II', 'Improved Healing III', 'Mana Preservation II', 'Reagent Conservation II', 'Extended Enhancement II'],
    "pal-mnk-ber/tank/focus": ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Extended Enhancement II', 'Mana Preservation II', 'Reagent Conservation II'],
    "pal-mnk-ber/melee/focus": ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Extended Enhancement II', 'Mana Preservation II', 'Reagent Conservation II'],
    "pal-mnk-ber/melee/click": ['Alacrity', 'Pillage Enchantment', 'Superior Healing', 'Spirit of Wolf', 'Spirit Tap', 'Raging Strength'],
}


def test_the_five_lists_that_the_mana_weight_of_the_templates_moved_are_the_earlier_ones_with_the_earlier_weight():
    catalog = json.loads((REPO / "derived" / "catalog.json").read_text(encoding="utf-8"))
    earlier = judgment_with_templates(tank={"MANA": 0.5}, melee={"MANA": 0.5})  # (the mana weight of those two templates before the builds; nothing else of them)
    made = files.build(catalog, sp.SpellBook.load(), earlier, "test")
    for key, was in BEFORE_THE_BUILDS.items():
        slug, role, kind = key.split("/")
        assert [o["name"] for o in lists(made, slug, role)[kind]] == was, key
        assert NOW[key] != was, key  # (and the lists of now are not these: the weight is what moved them)


def test_every_offered_role_of_the_example_trios_is_covered_here():
    covered = {key.rsplit("/", 1)[0] for key in NOW}
    assert covered == {f"pal-mnk-ber/{r}" for r in roles_for(["PAL", "MNK", "BER"])} | {f"clr-shd-shm/{r}" for r in roles_for(["CLR", "SHD", "SHM"])}


# ---- focus: one for each stacking type -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("slug", ["pal-mnk-ber", "clr-shd-shm", "wiz-mag-enc", "brd-nec-dru", "war-mnk-rog"])
def test_one_focus_for_each_stacking_type(built, slug):
    for role in roles_for([c.upper() for c in slug.split("-")]):
        focus = lists(built, slug, role)["focus"]
        types = [o["type"] for o in focus]
        assert len(types) == len(set(types))
        for option in focus:
            assert sp.focus_type(built.ctx.by_id[option["effect"]]["focus"]) == option["type"]


def test_the_haste_foci_share_one_type_and_only_spell_haste_wins_it_for_the_example_trios(built):
    haste = {sp.focus_type(e["focus"]) for e in built.effects if "focus" in e and e["focus"]["kind"] == "spell_haste"}
    assert haste == {"127"}  # Spell, Affliction, Enhancement, Reanimation and Summoning Haste are all effect id 127
    for slug in ("pal-mnk-ber", "clr-shd-shm"):
        focus = lists(built, slug, "tank")["focus"]
        winners = [o for o in focus if o["type"] in haste]
        assert [o["name"] for o in winners] == ["Spell Haste II"]
        assert winners[0]["losers"]  # the families that lost the type are kept for the "why not" note


# ---- dispel -------------------------------------------------------------------------------------------------------------------------------------------------


def pillage_rank(built, combo, role):
    names = [o["name"] for o in layer.layer(list(combo), role, built.ctx, top=False)["click"]]
    return names.index("Pillage Enchantment") + 1 if "Pillage Enchantment" in names else None


#: a build and a trio it is offered, for the example trios of the analysis and the other kinds of trio (every pair is a build the trio has: the test checks that, so that a pair
#: cannot stop testing anything)
PILLAGE_CASES = [
    ("clr-shd-shm", "tank"), ("clr-shd-shm", "shield"), ("clr-shd-shm", "melee"), ("clr-shd-shm", "caster"),
    ("wiz-mag-enc", "castertank"), ("wiz-mag-enc", "caster"), ("dru-shm-nec", "castertank"), ("dru-shm-nec", "caster"), ("enc-mag-clr", "castertank"), ("enc-mag-clr", "caster"),
    ("war-pal-shd", "tank"), ("pal-mnk-ber", "tank"), ("pal-mnk-ber", "melee"), ("brd-bst-rog", "melee"),
]  # fmt: skip


@pytest.mark.parametrize(("slug", "role"), PILLAGE_CASES)
def test_pillage_enchantment_is_in_the_top_3_clicks_of_a_build_the_example_trios_have(built, slug, role):
    combo = [c.upper() for c in slug.split("-")]
    assert role in roles_for(combo)
    assert pillage_rank(built, combo, role) <= 3


#: where Pillage Enchantment stands in the click list (1 is first) at the worst, for each build, over every trio the build is offered to (the Archer counted for every Ranger trio):
#: the real numbers of the lists of this port. It is in the top 3 for every trio of every build but the ones named in KNOWN_OUTSIDE_THE_TOP_3, where it is fourth
MOST_PILLAGE_RANK = {"tank": 3, "shield": 3, "melee": 4, "ranged": 4, "castertank": 1, "caster": 2}
OFFERED_TO = {"tank": 274, "shield": 210, "melee": 525, "ranged": 105, "castertank": 161, "caster": 224}
#: the trios that are the known exceptions: one trio of a Ranger, a Monk and a Magician for Melee damage and the Archer (the two Shield caster trios that were here, a Paladin and a Magician beside a
#: Monk or a Ranger, are in the top 3 since the mana weight of the Shield caster template fell from 1.5 to 0.3). A fourth place there is stated here, not left out: a new exception, or one that
#: goes, fails the test
KNOWN_OUTSIDE_THE_TOP_3 = {
    ("RNG", "MNK", "MAG"): {"melee": 4, "ranged": 4},
}


def test_pillage_enchantment_is_in_the_top_3_clicks_of_every_build_of_every_trio_but_the_known_exceptions(built):
    ranks = {}
    for combo in combinations(CLASS_CODES, 3):
        for role in roles_for(list(combo), bow=None):  # (every build a trio can have, the Archer for every Ranger trio)
            ranks[combo, role] = pillage_rank(built, combo, role)
    assert all(rank is not None for rank in ranks.values())  # (every list has it at all)
    for role, offered in OFFERED_TO.items():
        found = [rank for (combo, r), rank in ranks.items() if r == role]
        assert len(found) == offered, role
        assert max(found) == MOST_PILLAGE_RANK[role], role  # the bound that really holds for the build
    outside = {}
    for (combo, role), rank in ranks.items():
        if rank > 3:
            outside.setdefault(combo, {})[role] = rank
    assert outside == KNOWN_OUTSIDE_THE_TOP_3


def test_the_dispel_constant_is_the_one_place_that_sets_it(built):
    assert J.dispel_relevance == (0.6, 0.5, 0.7)
    lowered = dataclasses.replace(J, dispel_relevance=(0.1, 0.1, 0.1))
    ctx = layer.build_context(built.effects, sp.SpellBook.load(), lowered)
    names = [o["name"] for o in layer.layer(["CLR", "SHD", "SHM"], "caster", ctx, top=False)["click"]]
    assert names.index("Pillage Enchantment") + 1 > 3  # the constant, not the code, puts it in the top 3


def dispel_row(sid, name, slots, levels=None):
    return {"id": sid, "name": name, "cast_ms": 0, "mana": 0, "dur": [0, 0], "ben": 1, "res": 0, "tgt": 5, "lv": levels or {}, "fx": [[n, 27, 1, 0, 100, 0] for n in range(1, slots + 1)]}


def test_a_dispel_is_scored_by_the_buffs_it_strips_and_is_not_cut_for_the_trios_own_dispel():
    items = [
        ("one", ["EAR"], "click", "Strip One", "Effect: Strip One (Must Equip, Casting Time: Instant)"),
        ("four", ["FINGER"], "click", "Strip Four", "Effect: Strip Four (Must Equip, Casting Time: Instant)"),
    ]
    alone = synthetic(items, [dispel_row(1, "Strip One", 1), dispel_row(2, "Strip Four", 4)])
    owned = synthetic(items, [dispel_row(1, "Strip One", 1), dispel_row(2, "Strip Four", 4), dispel_row(3, "Cancel Magic", 1, {"WAR": 20})])
    trio = ["WAR", "MNK", "BER"]
    score = lambda ctx: {o["name"]: o["score"] for o in layer.layer(trio, "tank", ctx)["click"]}  # noqa: E731
    assert score(alone)["Strip Four"] > score(alone)["Strip One"] * 3  # four buffs against one
    assert score(owned)["Strip Four"] == score(alone)["Strip Four"]  # the trio's own Cancel Magic does not cut a click that strips more


# ---- Dismiss and Banish, Ykesha ---------------------------------------------------------------------------------------------------------------------------------------


def test_damage_that_works_on_some_targets_only_counts_a_fraction(built):
    undead = next(e for e in built.effects if e["name"] == "Dismiss Undead")
    assert undead["spell"]["target"] in J.restricted_targets
    assert layer._restricted(undead, "damage", J) == J.restricted_fraction < 1
    assert layer._restricted({"spell": {"target": 5}}, "damage", J) == 1.0
    assert layer._restricted(undead, "slow", J) == 1.0  # only damage kinds are cut


def test_banish_procs_no_longer_head_the_proc_list_of_a_cleric_trio(built):
    procs = [o["name"] for o in lists(built, "clr-shd-shm", "tank")["proc"]]
    assert "Banish Summoned" not in procs[:2] and "Banish Undead" not in procs[:2]


def test_ykesha_stays_a_small_damage_proc_marked_unverified(built):
    ykesha = [e for e in built.effects if e["name"] == "Ykesha"]
    assert ykesha and all(e["kind"] == "proc" and e["category"] == "damage" and e["unverified"] == ["description"] for e in ykesha)
    assert all(e["magnitude"] < 200 for e in ykesha)  # a small damage proc, as the spell data says
    shared = {row["n"]: row for row in files.shared_document(built)["effects"]}
    assert shared["Ykesha"]["x"] == ["description"]


# ---- guards ---------------------------------------------------------------------------------------------------------------------------------------------------------------


def synthetic(items, spell_rows):
    book = sp.SpellBook(spell_rows, 50)
    pool = [
        {
            "key": key, "name": key, "slots": slots, "classes": ["ALL"], "tier_rule": "drop", "weapon": None, "evidence": {"level": "wiki"},
            "effects": [{"kind": kind, "name": name, "raw": raw}], "sources": {"drops": [{"zone": "Lower Guk", "npcs": []}], "sold_by": [], "quests": [], "crafted": []},
        }
        for key, slots, kind, name, raw in items
    ]  # fmt: skip
    effects, _ = dn.build_effects(pool, book, J)
    return layer.build_context(effects, book, J)


def test_a_worn_haste_effect_is_never_offered_because_it_is_an_item_stat():
    row = {"id": 1, "name": "Swift", "cast_ms": 0, "mana": 0, "dur": [50, 0], "ben": 1, "res": 0, "tgt": 6, "lv": {}, "fx": [[1, 11, 150, 0, 100, 0]]}
    ctx = synthetic([("w1", ["FINGER"], "worn", "Swift", "Effect: Swift (Worn)")], [row])
    assert ctx.effects[0]["category"] == "haste"
    assert layer.layer(["WAR", "MNK", "BER"], "tank", ctx)["worn"] == []


def test_a_copy_with_a_required_level_above_the_cap_is_not_a_donor_but_a_copy_below_it_is():
    row = {"id": 1, "name": "Heal", "cast_ms": 0, "mana": 0, "dur": [0, 0], "ben": 1, "res": 0, "tgt": 5, "lv": {}, "fx": [[1, 0, 300, 0, 100, 0]]}
    ctx = synthetic(
        [
            ("hi", ["FINGER"], "click", "Heal", "Effect: Heal (Must Equip, Casting Time: Instant) req. level 55"),
            ("lo", ["EAR"], "click", "Heal", "Effect: Heal (Must Equip, Casting Time: Instant)"),
        ],
        [row],
    )
    options = layer.layer(["WAR", "MNK", "BER"], "tank", ctx)["click"]
    assert [(o["donor"], o["others"]) for o in options] == [("lo", [])]


def test_the_lists_are_the_same_every_time(built):
    a = lists(built, "clr-shd-shm", "tank")
    b = lists(built, "clr-shd-shm", "tank")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_the_rows_kept_are_the_rules(built):
    full = lists(built, "clr-shd-shm", "tank", top=False)
    cut = lists(built, "clr-shd-shm", "tank")
    for kind, count in J.rows_kept.items():
        assert cut[kind] == full[kind][:count]


def test_the_focus_ceiling_is_in_the_shared_file(built):
    shared = files.shared_document(built)
    haste = next(e for e in shared["effects"] if e["n"] == "Spell Haste II")
    assert haste["f"]["max"] == 44 and haste["f"]["pen"] == 5 and "weaker above" in haste["f"]["lim"]
    assert haste["f"]["cov"]["CLR"] > 50  # the share of a cleric's late spells it touches, with partial credit


def test_a_focus_row_says_what_each_trio_class_adds_and_the_sum_over_the_classes_that_wear_the_donor_is_its_score(built):
    classes = ["CLR", "SHD", "SHM"]
    for option in lists(built, "clr-shd-shm", "tank")["focus"]:
        donor = next(d for d in built.ctx.by_id[option["effect"]]["items"] if d["key"] == option["donor"])
        usable = dn.usable_by(donor, classes)
        assert set(option["gains"]) <= set(classes) and all(g > 0 for g in option["gains"].values())
        assert sum(option["gains"].get(c, 0) for c in usable) == pytest.approx(option["score"], abs=0.002)
    assert layer.focus_gain(built.ctx.by_id[option["effect"]], classes, classes, "tank", built.ctx) >= option["score"] - 0.002


def test_the_socket_tiers_of_the_plan_are_the_rule():
    from trioforge import rules

    assert layer.SLOT_TIER == rules.load().get("tier.socket_open")


# ---- the fix round: the foci's donors, the scales ----------------------------------------------------------------------------------------------------------------


def srow(sid, name, effects, ben=0, tgt=5, dur=(0, 0), levels=None, cast_ms=0, skill=0):
    return {"id": sid, "name": name, "cast_ms": cast_ms, "mana": 0, "dur": list(dur), "ben": ben, "res": 0, "tgt": tgt, "sk": skill, "lv": levels or {}, "fx": effects}


def sitem(key, slots, effects, classes=("ALL",), drops=("Lower Guk",)):
    return {
        "key": key, "name": key, "slots": slots, "classes": list(classes), "tier_rule": "drop", "weapon": None, "evidence": {"level": "wiki"},
        "effects": [{"kind": kind, "name": name, "raw": raw} for kind, name, raw in effects],
        "sources": {"drops": [{"zone": z, "npcs": []} for z in drops], "sold_by": [], "quests": [], "crafted": []},
    }  # fmt: skip


def context_of(pool, rows):
    book = sp.SpellBook(rows, 50)
    effects, _ = dn.build_effects(pool, book, J)
    return layer.build_context(effects, book, J)


NUKE = srow(900, "Nuke", [[1, 0, -200, 0, 100, 0]], levels={"WAR": 40}, cast_ms=3000)  # a spell a class casts, so that a focus has something to touch
HASTE_FOCUS = srow(901, "Quick", [[1, 127, 15, 0, 100, 0], [2, 143, 2000, 0, 100, 0]], ben=1)
TRIO = ["WAR", "MNK", "BER"]


def test_a_focus_copy_with_a_required_level_above_the_cap_is_no_donor(built):
    # review finding 1: the focus loop did not hold a donor to the required level, as the loops of the other kinds do
    pool = [
        sitem("hi", ["FINGER"], [("focus", "Quick", "Effect: Quick (Worn) req. level 55")]),
        sitem("lo", ["EAR"], [("focus", "Quick", "Effect: Quick (Worn)")]),
    ]
    options = layer.layer(TRIO, "tank", context_of(pool, [NUKE, HASTE_FOCUS]))["focus"]
    assert [(o["donor"], o["others"]) for o in options] == [("lo", [])]
    only_high = context_of(pool[:1], [NUKE, HASTE_FOCUS])
    assert layer.layer(TRIO, "tank", only_high)["focus"] == []


def test_the_click_scale_is_measured_against_effects_the_lists_can_offer():
    # review finding 2: a record with no copy that can be worn, and a record the lists treat as a proc, set the scale of the clicks
    heal = lambda sid, name, amount: srow(sid, name, [[1, 0, amount, 0, 100, 0]], ben=1)  # noqa: E731
    pool = [
        sitem("scroll", [], [("click", "Big Heal", "Effect: Big Heal (Must Equip, Casting Time: Instant)")]),  # nobody can wear a scroll
        sitem("late", ["EAR"], [("click", "Late Heal", "Effect: Late Heal (Must Equip, Casting Time: Instant) req. level 60")]),
        sitem("ring", ["FINGER"], [("click", "Small Heal", "Effect: Small Heal (Must Equip, Casting Time: Instant)")]),
        sitem("sword", ["PRIMARY"], [("other", "Big Nuke", "Effect: Big Nuke")]),  # no trigger wording on a weapon: a proc, not a click
        sitem("cloak", ["BACK"], [("click", "Small Nuke", "Effect: Small Nuke (Must Equip, Casting Time: Instant)")]),
    ]
    rows = [heal(1, "Big Heal", 5000), heal(2, "Late Heal", 3000), heal(3, "Small Heal", 300), srow(4, "Big Nuke", [[1, 0, -9000, 0, 100, 0]]), srow(5, "Small Nuke", [[1, 0, -100, 0, 100, 0]])]
    ctx = context_of(pool, rows)
    assert ctx.cat_max["heal"] == 300
    assert ctx.cat_max["damage"] == 100  # the 9000 is a proc's


def test_the_proc_scale_is_measured_in_the_size_a_proc_score_is_given():
    # review finding 3: a proc that works on some targets only counts a fraction in its score, and in the scale
    pool = [sitem(f"s{k}", ["PRIMARY"], [("proc", f"P{k}", f"Effect: P{k} (Combat)")]) for k in range(1, 11)]
    pool.append(sitem("undead", ["PRIMARY"], [("proc", "Banish", "Effect: Banish (Combat)")]))
    rows = [srow(k, f"P{k}", [[1, 0, -100 * k, 0, 100, 0]]) for k in range(1, 11)] + [srow(50, "Banish", [[1, 0, -1500, 0, 100, 0]], tgt=10)]
    ctx = context_of(pool, rows)
    assert ctx.proc_scale == pytest.approx(900)  # the second largest of 100 .. 1000 and 1500 x 0.35 = 525; undiscounted it would be 1000
    assert layer._restricted(ctx.by_id[next(e["id"] for e in ctx.effects if e["name"] == "Banish")], "damage", J) == J.restricted_fraction


def test_a_proc_only_counts_toward_the_scale_when_a_copy_can_be_worn():
    pool = [sitem("scroll", [], [("proc", "Poison", "Effect: Poison (Combat)")]), sitem("sword", ["PRIMARY"], [("proc", "Sting", "Effect: Sting (Combat)")])]
    rows = [srow(1, "Poison", [[1, 0, -9000, 0, 100, 0]]), srow(2, "Sting", [[1, 0, -50, 0, 100, 0]])]
    assert context_of(pool, rows).proc_scale == 50


def test_an_unlabelled_offensive_effect_is_a_proc_on_a_weapon_and_a_click_on_a_cloak_in_the_lists():
    # review finding 8, seen from the lists: each copy is offered as what it is
    pool = [sitem("sword", ["PRIMARY"], [("other", "Zap", "Effect: Zap")]), sitem("cloak", ["BACK"], [("other", "Zap", "Effect: Zap (Must Equip)")])]
    ctx = context_of(pool, [srow(1, "Zap", [[1, 0, -300, 0, 100, 0]])])
    lists_ = layer.layer(TRIO, "tank", ctx)
    assert [o["donor"] for o in lists_["click"]] == ["cloak"]
    assert [dn.kind_of(e) for e in ctx.effects] == ["click", "proc"] and all(len({dn.kind_of(e)}) == 1 for e in ctx.effects)
    # (G5) the copy on the sword is a proc, marked as inferred (no wording says when it fires), which the rule counts for nothing in the solver's table; the lists score a record by the table's value, so it
    # is worth nothing in them and is not listed (before, the lists scored it as a damage proc of 300)
    (proc,) = [e for e in ctx.effects if dn.kind_of(e) == "proc"]
    assert "inferred" in (proc.get("unverified") or ()) and lists_["proc"] == []


# ---- the weights of a build in the lists are read against the largest templates of the rules, not against constants ----------------------------------------------------


def judgment_with_templates(**changes):
    """The judgment of the rules file with the templates of ``changes`` ({build: {key: number}}) put over those of the rules."""
    from trioforge.rules import load

    data = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))
    (templates,) = [rule for rule in data["rules"] if rule["id"] == "roles.templates"]
    for build, row in changes.items():
        templates["value"][build].update(row)
    from trioforge.rules import Rules

    assert load().version == data["version"]
    return judgment.Judgment.from_rules(Rules(data))


def test_the_mana_and_attack_weights_of_a_build_are_shares_of_the_largest_in_the_templates():
    classes = ["PAL", "MNK", "BER"]
    mana = {role: layer.role_rel(role, classes, J)[1] for role in ("tank", "shield", "melee", "ranged", "castertank", "caster")}
    attack = {role: layer.role_rel(role, classes, J)[2] for role in mana}
    templates = J.templates
    assert max(mana.values()) == pytest.approx(1.0) and max(attack.values()) == pytest.approx(1.0)  # (the Caster has the largest mana weight, Melee damage the largest attack weight)
    assert mana["caster"] == pytest.approx(1.0) and attack["melee"] == pytest.approx(1.0)
    assert attack["tank"] == pytest.approx(templates["tank"]["ATK"] / templates["melee"]["ATK"])
    assert mana["shield"] == pytest.approx(templates["shield"]["MANA"] / templates["caster"]["MANA"])


def test_a_template_larger_than_the_old_constants_does_not_push_a_weight_over_one():
    big = judgment_with_templates(melee={"ATK": 6}, caster={"MANA": 8})
    classes = ["PAL", "MNK", "BER"]
    assert layer.role_rel("melee", classes, big)[2] == pytest.approx(1.0)  # (it was 6 / 3 = 2 with the constant 3)
    assert layer.role_rel("caster", classes, big)[1] == pytest.approx(1.0)  # (it was 8 / 4 = 2 with the constant 4)
    assert layer.role_rel("tank", classes, big)[2] == pytest.approx(2.67 / 6)
    assert layer.role_rel("shield", classes, big)[1] == pytest.approx(0.3 / 8)


# ---- fix round 2: no mean for a build that is not one, and a clear error where the templates have no mana or no attack to take a share of ---------------------------


@pytest.mark.parametrize("role", [None, "balanced", "healer", ""])
def test_the_relevance_of_a_kind_of_click_is_asked_of_a_build_and_a_build_that_is_not_one_is_refused(role):
    groups = layer.ROLE_GROUPS
    for kind in ("dispel", "other", "haste"):
        with pytest.raises(ValueError, match="build"):
            J.relevance_of(kind, role, ["PAL", "MNK", "BER"], groups)
    for build in ("tank", "shield", "melee", "ranged", "castertank", "caster"):
        assert 0 <= J.relevance_of("other", build, ["PAL", "MNK", "BER"], groups) <= 1  # (every build has its column)


@pytest.mark.parametrize("key", ["MANA", "ATK"])
def test_a_share_of_the_largest_template_weight_needs_a_weight_above_zero_and_says_so(key):
    zero = judgment_with_templates(**{build: {key: 0} for build in ("tank", "shield", "melee", "castertank", "caster")})  # (the Archer is the Melee template, with factors)
    with pytest.raises(ValueError, match=rf"{key}.*template"):
        layer.role_rel("tank", ["PAL", "MNK", "BER"], zero)
    with pytest.raises(ValueError, match=rf"{key}.*template"):
        layer.role_rel(None, ["PAL", "MNK", "BER"], zero)  # (the mean over the builds of the trio takes the same shares)
