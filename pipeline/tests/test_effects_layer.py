"""Tests for the ranked lists of the effects layer, on the real catalog and the client's spell text (``derived/``): the order the analysis found for the two example
trios, the order the three fixes and the dispel change give, one focus for each stacking type, the dispel constant, and the guards."""

import dataclasses
import json
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
# ANALYSIS is the order of the private analysis of 2026-10-22 (r2) before the review's fixes, NOW the order of this port. With every fix reverted the port gives the
# analysis' lists for all 560 trios and every role (checked when the port was written); the differences below are the fixes' and nothing else:
#
# * focus (partial credit for a spell above a focus's maximum level): Reagent Conservation III is no longer the pick, because Reagent Conservation II, the easier
#   source, now keeps most of its coverage (it is within 90 percent of III); the tier-II foci lose a few points of coverage, which moves Extended Range II above
#   Improved Healing III in clr-shd-shm and Mana Preservation II below Extended Enhancement II in pal-mnk-ber;
# * (hit points spent for mana, counted as mana: Cannibalize I and II, Dark Pact, Allure of Death, Call of Bones and Lich) alone this puts Improved Damage III over
#   Burning Affliction II in the caster role of clr-shd-shm; together with the partial credit the order is the analysis' again;
# * click (the dispel constant): Pillage Enchantment, a must-equip dispel that strips four buffs, is now in the top 3 for the caster and balanced roles;
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

NOW = {
    'pal-mnk-ber/balanced/focus': ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Extended Enhancement II', 'Mana Preservation II', 'Reagent Conservation II'],
    'pal-mnk-ber/balanced/click': ['Alacrity', 'Pillage Enchantment', 'Superior Healing', 'Spirit of Wolf', 'Spirit Tap', 'Raging Strength'],
    'pal-mnk-ber/balanced/carry': ['Walking Sleep', 'Levitate', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV', 'Healing', 'Breath of the Dead'],
    'pal-mnk-ber/balanced/worn': ['Unrighteous Bash', 'Virtuous Bash', 'Heritage of Mistmoore'],
    'pal-mnk-ber/balanced/proc': ["Oathbreaker's Curse", 'Earthquake', 'Flame Shock', 'Cleanse', 'Haste', 'Haste'],
    'pal-mnk-ber/tank/focus': ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Extended Enhancement II', 'Mana Preservation II', 'Reagent Conservation II'],
    'pal-mnk-ber/tank/click': ['Alacrity', 'Pillage Enchantment', 'Superior Healing', 'Spirit of Wolf', 'Spirit Tap', 'Raging Strength'],
    'pal-mnk-ber/tank/carry': ['Walking Sleep', 'Bramblecoat', 'Divine Aura', 'Levitate', 'Rune I', 'Rune IV', 'Healing', 'Breath of the Dead'],
    'pal-mnk-ber/tank/worn': ['Unrighteous Bash', 'Virtuous Bash', 'Heritage of Mistmoore'],
    'pal-mnk-ber/tank/proc': ["Oathbreaker's Curse", 'Earthquake', 'Flame Shock', 'Cleanse', 'Haste', 'Haste'],
    'pal-mnk-ber/melee/focus': ['Spell Haste II', 'Improved Damage III', 'Improved Healing III', 'Extended Range II', 'Extended Enhancement II', 'Mana Preservation II', 'Reagent Conservation II'],
    'pal-mnk-ber/melee/click': ['Alacrity', 'Pillage Enchantment', 'Superior Healing', 'Spirit of Wolf', 'Spirit Tap', 'Raging Strength'],
    'pal-mnk-ber/melee/carry': ['Walking Sleep', 'Levitate', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV', 'Breath of the Dead', 'Enduring Breath'],
    'pal-mnk-ber/melee/worn': ['Unrighteous Bash', 'Virtuous Bash', 'Heritage of Mistmoore'],
    'pal-mnk-ber/melee/proc': ["Oathbreaker's Curse", 'Earthquake', 'Flame Shock', 'Cleanse', 'Haste', 'Haste'],
    'clr-shd-shm/balanced/focus': ['Spell Haste II', 'Improved Damage III', 'Extended Range II', 'Improved Healing III', 'Mana Preservation II', 'Reagent Conservation II', 'Extended Enhancement II'],
    'clr-shd-shm/balanced/click': ['Pillage Enchantment', 'Superior Healing', 'Spirit Tap', 'Rune III', 'Restore Sight', 'Calm'],
    'clr-shd-shm/balanced/carry': ['Walking Sleep', 'Mana Convert', 'Word of Health', 'Malaisement', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV'],
    'clr-shd-shm/balanced/worn': ['Heritage of Mistmoore', 'Unrighteous Bash', 'See Invisible'],
    'clr-shd-shm/balanced/proc': ['Heat Blood', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Earthquake', 'Cleanse'],
    'clr-shd-shm/tank/focus': ['Spell Haste II', 'Improved Damage III', 'Extended Range II', 'Improved Healing III', 'Mana Preservation II', 'Reagent Conservation II', 'Extended Enhancement II'],
    'clr-shd-shm/tank/click': ['Pillage Enchantment', 'Superior Healing', 'Spirit Tap', 'Rune III', 'Restore Sight', 'Calm'],
    'clr-shd-shm/tank/carry': ['Walking Sleep', 'Word of Health', 'Malaisement', 'Mana Convert', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV'],
    'clr-shd-shm/tank/worn': ['Unrighteous Bash', 'Heritage of Mistmoore', 'See Invisible'],
    'clr-shd-shm/tank/proc': ['Heat Blood', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Earthquake', 'Cleanse'],
    'clr-shd-shm/melee/focus': ['Spell Haste II', 'Improved Damage III', 'Extended Range II', 'Improved Healing III', 'Mana Preservation II', 'Reagent Conservation II', 'Extended Enhancement II'],
    'clr-shd-shm/melee/click': ['Pillage Enchantment', 'Superior Healing', 'Spirit Tap', 'Rune III', 'Alacrity', 'Restore Sight'],
    'clr-shd-shm/melee/carry': ['Walking Sleep', 'Word of Health', 'Malaisement', 'Mana Convert', 'Bramblecoat', 'Divine Aura', 'Rune I', 'Rune IV'],
    'clr-shd-shm/melee/worn': ['Unrighteous Bash', 'Heritage of Mistmoore', 'See Invisible'],
    'clr-shd-shm/melee/proc': ['Heat Blood', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Earthquake', 'Cleanse'],
    'clr-shd-shm/caster/focus': ['Spell Haste II', 'Mana Preservation II', 'Burning Affliction II', 'Improved Healing III', 'Extended Range II', 'Reagent Conservation II', 'Extended Enhancement II'],
    'clr-shd-shm/caster/click': ['Pillage Enchantment', 'Superior Healing', 'Restore Sight', 'Spirit Tap', 'Calm', 'Lull'],
    'clr-shd-shm/caster/carry': ['Mana Convert', 'Walking Sleep', 'Malaisement', 'Word of Health', 'Illusion: Tree', 'Fear', 'Companion Spirit', 'Healing'],
    'clr-shd-shm/caster/worn': ['Heritage of Mistmoore', 'See Invisible', 'Enduring Breath'],
    'clr-shd-shm/caster/proc': ['Heat Blood', "Oathbreaker's Curse", 'Scourge', "Winter's Roar", 'Earthquake', 'Cleanse'],
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
    assert [o["name"] for o in lists(built, slug, role)[kind]] == NOW[key]


@pytest.mark.parametrize("key", sorted(NOW))
def test_a_list_differs_from_the_analysis_only_where_a_fix_changes_it(key):
    kind = key.split("/")[2]
    if NOW[key] != ANALYSIS[key]:
        assert kind in REASON, f"{key} changed and no fix explains it"


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
        focus = lists(built, slug, "balanced")["focus"]
        winners = [o for o in focus if o["type"] in haste]
        assert [o["name"] for o in winners] == ["Spell Haste II"]
        assert winners[0]["losers"]  # the families that lost the type are kept for the "why not" note


# ---- dispel -------------------------------------------------------------------------------------------------------------------------------------------------


def pillage_rank(built, combo, role):
    names = [o["name"] for o in layer.layer(list(combo), role, built.ctx, top=False)["click"]]
    return names.index("Pillage Enchantment") + 1 if "Pillage Enchantment" in names else None


@pytest.mark.parametrize("slug", ["clr-shd-shm", "wiz-mag-enc", "dru-shm-nec", "enc-mag-clr", "war-pal-shd", "pal-mnk-ber", "brd-bst-rog"])
def test_pillage_enchantment_is_in_the_top_3_clicks_of_the_caster_and_balanced_roles(built, slug):
    combo = [c.upper() for c in slug.split("-")]
    for role in roles_for(combo):
        if role in ("balanced", "caster"):
            assert pillage_rank(built, combo, role) <= 3


def test_pillage_enchantment_is_in_the_top_3_clicks_of_every_balanced_and_every_caster_role(built):
    ranks = {}
    for combo in combinations(CLASS_CODES, 3):
        for role in roles_for(list(combo)):
            if role in ("balanced", "caster"):
                ranks[combo, role] = pillage_rank(built, combo, role)
    assert len(ranks) == 560 + 441
    assert max(ranks.values()) <= 3


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
    score = lambda ctx: {o["name"]: o["score"] for o in layer.layer(trio, "balanced", ctx)["click"]}  # noqa: E731
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
    procs = [o["name"] for o in lists(built, "clr-shd-shm", "balanced")["proc"]]
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
    assert layer.layer(["WAR", "MNK", "BER"], "balanced", ctx)["worn"] == []


def test_a_copy_with_a_required_level_above_the_cap_is_not_a_donor_but_a_copy_below_it_is():
    row = {"id": 1, "name": "Heal", "cast_ms": 0, "mana": 0, "dur": [0, 0], "ben": 1, "res": 0, "tgt": 5, "lv": {}, "fx": [[1, 0, 300, 0, 100, 0]]}
    ctx = synthetic(
        [
            ("hi", ["FINGER"], "click", "Heal", "Effect: Heal (Must Equip, Casting Time: Instant) req. level 55"),
            ("lo", ["EAR"], "click", "Heal", "Effect: Heal (Must Equip, Casting Time: Instant)"),
        ],
        [row],
    )
    options = layer.layer(["WAR", "MNK", "BER"], "balanced", ctx)["click"]
    assert [(o["donor"], o["others"]) for o in options] == [("lo", [])]


def test_the_lists_are_the_same_every_time(built):
    a = lists(built, "clr-shd-shm", "balanced")
    b = lists(built, "clr-shd-shm", "balanced")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_the_rows_kept_are_the_rules(built):
    full = lists(built, "clr-shd-shm", "balanced", top=False)
    cut = lists(built, "clr-shd-shm", "balanced")
    for kind, count in J.rows_kept.items():
        assert cut[kind] == full[kind][:count]


def test_the_focus_ceiling_is_in_the_shared_file(built):
    shared = files.shared_document(built)
    haste = next(e for e in shared["effects"] if e["n"] == "Spell Haste II")
    assert haste["f"]["max"] == 44 and haste["f"]["pen"] == 5 and "weaker above" in haste["f"]["lim"]
    assert haste["f"]["cov"]["CLR"] > 50  # the share of a cleric's late spells it touches, with partial credit


def test_a_focus_row_says_what_each_trio_class_adds_and_the_sum_over_the_classes_that_wear_the_donor_is_its_score(built):
    classes = ["CLR", "SHD", "SHM"]
    for option in lists(built, "clr-shd-shm", "balanced")["focus"]:
        donor = next(d for d in built.ctx.by_id[option["effect"]]["items"] if d["key"] == option["donor"])
        usable = dn.usable_by(donor, classes)
        assert set(option["gains"]) <= set(classes) and all(g > 0 for g in option["gains"].values())
        assert sum(option["gains"].get(c, 0) for c in usable) == pytest.approx(option["score"], abs=0.002)
    assert layer.focus_gain(built.ctx.by_id[option["effect"]], classes, classes, "balanced", built.ctx) >= option["score"] - 0.002


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
    options = layer.layer(TRIO, "balanced", context_of(pool, [NUKE, HASTE_FOCUS]))["focus"]
    assert [(o["donor"], o["others"]) for o in options] == [("lo", [])]
    only_high = context_of(pool[:1], [NUKE, HASTE_FOCUS])
    assert layer.layer(TRIO, "balanced", only_high)["focus"] == []


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
    lists_ = layer.layer(TRIO, "balanced", ctx)
    assert [o["donor"] for o in lists_["proc"]] == ["sword"] and [o["donor"] for o in lists_["click"]] == ["cloak"]
    assert [dn.kind_of(e) for e in ctx.effects] == ["click", "proc"] and all(len({dn.kind_of(e)}) == 1 for e in ctx.effects)
