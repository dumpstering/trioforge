"""Tests for the buff engine: own buffs, the common group preset, stacking and conflict resolution.

The unit tests use synthetic spell records in the shape of ``derived/client/spells-l50.json`` (an id, a
name, the classes that get the spell, a target type, a duration, the effect slots with their values and
the 148/149 stacking commands) under invented names. The exactness properties check the whole resolution
against brute force over random pools of such buffs, with conflicts, costs, a limit on active buffs and a
random objective that never falls when a total rises. The integration tests read the committed
``derived/client`` files.
"""

import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from trioforge.model import buffs as bf
from trioforge.model.buffs import Buff, BuffSet, exclusions, group_preset, own_buffs, resolve
from trioforge.rules import load as load_rules

REPO_ROOT = Path(__file__).resolve().parents[2]
DERIVED = REPO_ROOT / "derived" / "client"

SPA = {
    "HPREG": 0, "AC": 1, "ATK": 2, "STR": 4, "DEX": 5, "AGI": 6, "STA": 7, "INT": 8, "WIS": 9, "CHA": 10,
    "HASTE": 11, "MANAREG": 15, "FIRE": 46, "COLD": 47, "POISON": 48, "DISEASE": 49, "MAGIC": 50,
    "HP": 69, "MANA": 97, "ALLRES": 111, "ENDREG": 189, "END": 190,
}  # fmt: skip
ILLUSION, ROOT, INSTANT_HP, RUN_SPEED = 58, 99, 79, 3


def fx(slot, what, value):
    """One effect slot of a synthetic spell: ``what`` is a name of :data:`SPA` or a raw effect id."""
    spa = SPA[what] if isinstance(what, str) else what
    return {
        "slot": slot, "spa": spa, "name": str(what), "base": value, "limit": 0, "formula": 100, "max": value,
        "value": value,
    }  # fmt: skip


def spell(sid, name, effects, *, classes=None, target=51, ticks=720, permanent=False, stacking=()):
    """A spell record as ``read_beneficial`` writes it; ``effects`` is a list of (slot, what, value)."""
    return {
        "id": sid,
        "name": name,
        "classes": dict(classes or {"SHM": 40}),
        "target": target,
        "duration_ticks": None if permanent else ticks,
        "permanent": permanent,
        "effects": [fx(*effect) for effect in effects],
        "stacking": [dict(entry) for entry in stacking],
    }


def command(kind, effect, slot, threshold=None, at=9):
    """A 148/149 stacking command: it looks at ``slot`` of the other spell for ``effect``."""
    entry = {"slot": at, "spa": kind, "kind": str(kind), "base": effect, "limit": slot}
    if threshold is not None:
        entry["max"] = threshold
    return entry


def buff(sid, name, effects, **kwargs):
    return Buff.from_spell(spell(sid, name, effects, **kwargs))


def ids(buffs):
    return tuple(b.id for b in buffs)


RULES = load_rules()


# ---- the vector of a buff ------------------------------------------------------------------------------------


def test_effects_become_stat_and_resist_components():
    b = buff(
        1,
        "Alpha Ward",
        [
            (1, "STR", 50), (2, "AC", 30), (3, "HP", 250), (4, INSTANT_HP, 250), (5, "FIRE", 20), (6, "MANAREG", 9),
            (7, "HASTE", 140), (8, "ATK", 15), (9, "HPREG", 4), (10, "ENDREG", 3),
        ],
    )  # fmt: skip
    assert b.stats == {
        "AC": 30, "STR": 50, "STA": 0, "AGI": 0, "DEX": 0, "WIS": 0, "INT": 0, "CHA": 0, "HP": 250, "MANA": 0,
        "END": 0, "ATK": 15, "HPREG": 4, "MANAREG": 9, "ENDREG": 3,
    }  # fmt: skip
    assert b.sv == {"FIRE": 20, "COLD": 0, "MAGIC": 0, "POISON": 0, "DISEASE": 0}
    assert b.haste == 40


def test_each_resist_effect_feeds_its_own_school_and_all_resists_feeds_all_five():
    schools = [(1, "FIRE", 10), (2, "COLD", 20), (3, "POISON", 30), (4, "DISEASE", 40), (5, "MAGIC", 50)]
    b = buff(1, "Beta Ward", schools)
    assert b.sv == {"FIRE": 10, "COLD": 20, "MAGIC": 50, "POISON": 30, "DISEASE": 40}
    every = buff(2, "Gamma Ward", [(1, "ALLRES", 20), (2, "FIRE", 5)])
    assert every.sv == {"FIRE": 25, "COLD": 20, "MAGIC": 20, "POISON": 20, "DISEASE": 20}


def test_haste_is_the_attack_speed_over_100_and_a_slow_gives_none():
    assert buff(1, "Fast", [(1, "HASTE", 140)]).haste == 40
    assert buff(2, "Even", [(1, "HASTE", 100)]).haste == 0
    assert buff(3, "Slow", [(1, "HASTE", 70), (2, "STR", 5)]).haste == 0


def test_effects_of_one_kind_add_up_inside_a_spell_but_haste_takes_the_best():
    b = buff(1, "Delta", [(1, "STR", 10), (2, "STR", 20), (3, "HASTE", 125), (4, "HASTE", 140)])
    assert b.stats["STR"] == 30
    assert b.haste == 40


def test_effects_the_model_does_not_score_are_kept_for_stacking_only():
    b = buff(1, "Epsilon", [(1, "STR", 10), (2, RUN_SPEED, 55)])
    assert b.stats["STR"] == 10
    assert (2, RUN_SPEED, 55) in b.effects


def test_limit_effects_with_no_value_are_not_effects():
    record = spell(1, "Zeta", [(1, "STR", 10)])
    record["effects"].append({**fx(2, 134, 0), "name": "LIMIT", "value": None})
    b = Buff.from_spell(record)
    assert b.stats["STR"] == 10
    assert all(spa != 134 for _, spa, _ in b.effects)
    assert all(spa != 134 for _, spa in b.keys)


def test_a_scored_effect_without_a_value_cannot_make_a_buff():
    record = spell(1, "Eta", [(1, "STR", 10)])
    record["effects"][0]["value"] = None
    with pytest.raises(ValueError, match="value"):
        Buff.from_spell(record)


def test_illusions_are_flagged_and_classes_are_listed_in_class_order():
    b = buff(1, "Theta Shape", [(1, ILLUSION, 796), (2, "ATK", 30)], classes={"DRU": 30, "RNG": 48})
    assert b.illusion is True
    assert b.classes == (("RNG", 48), ("DRU", 30))
    assert buff(2, "Iota", [(1, "STR", 1)]).illusion is False


def test_a_buff_is_frozen_and_hashable():
    b = buff(1, "Kappa", [(1, "STR", 10)])
    assert hash(b) == hash(buff(1, "Kappa", [(1, "STR", 10)]))
    with pytest.raises(AttributeError):
        b.name = "other"  # type: ignore[misc]


def test_stacking_commands_are_read_with_their_threshold():
    b = buff(
        1, "Lambda", [(1, "HP", 251), (4, "STR", 67)],
        stacking=[command(149, 4, 1, 67), command(148, 4, 1, 1067), command(148, 5, 1)],
    )  # fmt: skip
    assert set(b.commands) == {(149, 4, 1, 67), (148, 4, 1, 1067), (148, 5, 1, None)}


# ---- what stops two buffs from standing together ---------------------------------------------------------------


def test_the_same_slot_and_the_same_effect_exclude():
    a = buff(1, "Mu", [(1, "STR", 50)])
    b = buff(2, "Nu", [(1, "STR", 67)])
    assert exclusions(a, b) == ("slot1/spa4",)
    assert exclusions(b, a) == ("slot1/spa4",)


def test_another_slot_or_another_effect_stacks():
    assert exclusions(buff(1, "Xi", [(1, "STR", 50)]), buff(2, "Omicron", [(2, "STR", 40)])) == ()
    assert exclusions(buff(3, "Pi", [(1, "STR", 50)]), buff(4, "Rho", [(1, "DEX", 40)])) == ()


def test_instant_hit_points_and_limit_slots_never_collide():
    a = buff(1, "Sigma", [(1, "STR", 5), (3, INSTANT_HP, 250)])
    b = buff(2, "Tau", [(2, "DEX", 5), (3, INSTANT_HP, 300)])
    assert exclusions(a, b) == ()
    c = Buff.from_spell({**spell(3, "Upsilon", [(1, "AC", 5)]), "effects": [fx(1, "AC", 5), fx(2, 134, 0)]})
    d = Buff.from_spell({**spell(4, "Phi", [(1, "ATK", 5)]), "effects": [fx(1, "ATK", 5), fx(2, 134, 0)]})
    assert exclusions(c, d) == ()


def test_only_one_spell_haste_counts_so_two_haste_buffs_exclude():
    a = buff(1, "Chi", [(1, "HASTE", 125), (2, "AGI", 30)])
    b = buff(2, "Psi", [(3, "HASTE", 140), (4, "AC", 10)])
    assert exclusions(a, b) == ("haste",)
    assert exclusions(a, buff(3, "Omega", [(1, "STR", 5)])) == ()


def test_two_illusions_exclude_each_other_whatever_their_slots():
    a = buff(1, "Wolfish", [(1, ILLUSION, 796), (2, "ATK", 30)])
    b = buff(2, "Bearish", [(3, ILLUSION, 43), (4, "WIS", 5)])
    assert exclusions(a, b) == ("illusion",)


def test_reasons_are_listed_once_and_sorted():
    a = buff(1, "A1", [(1, "STR", 50), (2, "AC", 10), (3, ILLUSION, 5), (4, "HASTE", 120)])
    b = buff(2, "B1", [(1, "STR", 40), (2, "AC", 30), (5, ILLUSION, 6), (6, "HASTE", 130)])
    assert exclusions(a, b) == ("haste", "illusion", "slot1/spa4", "slot2/spa1")


@pytest.mark.parametrize(
    ("other_value", "raw", "mod1000"),
    [(66, True, True), (67, True, False), (68, True, False)],
)
def test_a_threshold_of_1000_or_more_reads_as_stored_or_modulo_1000(other_value, raw, mod1000):
    # The combined spell blocks a one-stat spell in slot 1 whose value is below 1067 (raw) or below 67 (modulo 1000).
    combined = buff(1, "Combined", [(4, "STR", 67)], stacking=[command(148, 4, 1, 1067)])
    single = buff(2, "Single", [(1, "STR", other_value)])
    assert bool(exclusions(combined, single, decode="raw")) is raw
    assert bool(exclusions(combined, single, decode="mod1000")) is mod1000


def test_a_threshold_below_1000_is_the_same_in_both_readings():
    owner = buff(1, "Owner", [(2, "AC", 30)], stacking=[command(149, 1, 3, 100)])
    below = buff(2, "Below", [(1, "STR", 5), (2, "DEX", 5), (3, "AC", 99)])
    equal = buff(3, "Equal", [(1, "STR", 5), (2, "DEX", 5), (3, "AC", 100)])
    for decode in ("raw", "mod1000"):
        assert exclusions(owner, below, decode=decode) == ("cmd149/slot3/spa1",)
        assert exclusions(owner, equal, decode=decode) == ()


def test_a_command_with_no_threshold_matches_any_value_in_the_named_slot():
    owner = buff(1, "Owner", [(2, "AC", 30)], stacking=[command(148, 1, 3)])
    other = buff(2, "Other", [(3, "AC", 5000)])
    elsewhere = buff(3, "Elsewhere", [(4, "AC", 5)])
    assert exclusions(owner, other) == ("cmd148/slot3/spa1",)
    assert exclusions(owner, elsewhere) == ()


def test_a_command_only_looks_at_the_slot_and_the_effect_it_names():
    owner = buff(1, "Owner", [(5, "STR", 67)], stacking=[command(148, 4, 1, 1067)])
    assert exclusions(owner, buff(2, "Wrong slot", [(2, "STR", 10)])) == ()
    assert exclusions(owner, buff(3, "Wrong effect", [(1, "DEX", 10)])) == ()


def test_commands_exclude_in_both_directions():
    owner = buff(1, "Owner", [(5, "STR", 67)], stacking=[command(148, 4, 1, 1067)])
    other = buff(2, "Other", [(1, "STR", 10)])
    assert exclusions(owner, other) == exclusions(other, owner) == ("cmd148/slot1/spa4",)


def test_an_unknown_reading_of_the_thresholds_is_refused():
    a, b = buff(1, "A", [(1, "STR", 1)]), buff(2, "B", [(2, "STR", 1)])
    with pytest.raises(ValueError, match="decode"):
        exclusions(a, b, decode="guess")
    with pytest.raises(ValueError, match="decode"):
        resolve([a, b], decode="guess")


# ---- resolving a set of buffs ----------------------------------------------------------------------------------


def test_the_higher_buff_in_a_shared_slot_dominates_and_only_it_is_always_on():
    low = buff(1, "Low", [(1, "STR", 50)])
    high = buff(2, "High", [(1, "STR", 67)])
    bs = resolve([low, high])
    assert ids(bs.always_on) == (2,)
    assert bs.optional == () and bs.conflicts == () and bs.cardinality is None
    assert [(d.id, d.reason, d.by) for d in bs.dropped] == [(1, "dominated", 2)]
    assert bs.totals()["STR"] == 67


def test_different_effects_in_one_slot_are_both_on():
    bs = resolve([buff(1, "A", [(1, "STR", 50)]), buff(2, "B", [(1, "DEX", 40)])])
    assert ids(bs.always_on) == (1, 2)
    totals = bs.totals()
    assert (totals["STR"], totals["DEX"]) == (50, 40)


def test_the_same_effect_in_other_slots_adds_up():
    bs = resolve([buff(1, "A", [(1, "STR", 50)]), buff(2, "B", [(2, "STR", 40)])])
    assert ids(bs.always_on) == (1, 2)
    assert bs.totals()["STR"] == 90


def test_two_conflicting_buffs_where_neither_dominates_make_one_pair():
    a = buff(1, "A", [(1, "STR", 50), (2, "AC", 10)])
    b = buff(2, "B", [(1, "STR", 40), (3, "AC", 30)])
    bs = resolve([a, b])
    assert bs.always_on == ()
    assert ids(bs.optional) == (1, 2)
    assert bs.conflicts == ((1, 2),)
    assert bs.reasons(1, 2) == ("slot1/spa4",) and bs.reasons(2, 1) == ("slot1/spa4",)
    assert bs.cardinality is None and bs.dropped == ()
    assert bs.cliques == ((1, 2),)


def test_only_the_best_spell_haste_counts():
    slow, fast = buff(1, "Slow Haste", [(1, "HASTE", 125)]), buff(2, "Fast Haste", [(1, "HASTE", 140)])
    bs = resolve([slow, fast])
    assert ids(bs.always_on) == (2,)
    assert [(d.id, d.by) for d in bs.dropped] == [(1, 2)]
    assert bs.totals()["haste"] == 40


def test_haste_buffs_in_other_slots_still_exclude_when_neither_dominates():
    a = buff(1, "A", [(1, "HASTE", 125), (2, "AGI", 30)])
    b = buff(2, "B", [(3, "HASTE", 140), (4, "AC", 10)])
    bs = resolve([a, b])
    assert bs.conflicts == ((1, 2),) and bs.reasons(1, 2) == ("haste",)
    assert not bs.is_legal((1, 2))
    assert bs.totals((1,))["haste"] == 25 and bs.totals((2,))["haste"] == 40


def test_totals_count_a_haste_pair_once_even_when_the_caller_forces_both():
    a = buff(1, "A", [(1, "HASTE", 125), (2, "AGI", 30)])
    b = buff(2, "B", [(3, "HASTE", 140), (4, "AC", 10)])
    totals = resolve([a, b]).totals((1, 2))
    assert totals["haste"] == 40 and totals["AGI"] == 30 and totals["AC"] == 10


def test_an_illusion_pair_excludes():
    a = buff(1, "Wolfish", [(1, ILLUSION, 796), (2, "ATK", 30)])
    b = buff(2, "Bearish", [(3, ILLUSION, 43), (4, "WIS", 5)])
    bs = resolve([a, b])
    assert bs.conflicts == ((1, 2),) and bs.reasons(1, 2) == ("illusion",)
    assert all(x.illusion for x in bs.optional)


def test_a_cardinality_row_is_reported_when_the_limit_can_bind():
    three = [buff(1, "A", [(1, "STR", 5)]), buff(2, "B", [(1, "DEX", 5)]), buff(3, "C", [(1, "AGI", 5)])]
    bs = resolve(three, max_slots=2)
    assert bs.cardinality == 2
    assert bs.always_on == () and ids(bs.optional) == (1, 2, 3) and bs.conflicts == ()
    assert [ids_ for ids_ in bs.iter_legal() if len(ids_) == 3] == []
    slack = resolve(three, max_slots=3)
    assert slack.cardinality is None and ids(slack.always_on) == (1, 2, 3)


def test_the_limit_does_not_bind_when_conflicts_keep_the_active_count_under_it():
    a = buff(1, "A", [(1, "STR", 50), (2, "AC", 10)])
    b = buff(2, "B", [(1, "STR", 40), (3, "AC", 30)])
    c = buff(3, "C", [(1, "DEX", 5)])
    bs = resolve([a, b, c], max_slots=2)  # at most two can stand together, so the limit never cuts
    assert bs.cardinality is None
    assert ids(bs.always_on) == (3,) and ids(bs.optional) == (1, 2)


def test_the_limit_comes_from_the_rules_file_unless_given():
    many = [buff(i, f"Buff {i}", [(i, "STR", 5)]) for i in range(1, 18)]  # 17 buffs that all stack
    assert resolve(many, RULES).cardinality == RULES.get("buffs.max_slots") == 15
    assert resolve(many, RULES, max_slots=17).cardinality is None
    assert resolve(many).cardinality is None


def test_resolving_nothing_gives_an_empty_set():
    bs = resolve([])
    assert bs == BuffSet((), (), (), (), (), None, ())
    assert bs.totals()["STR"] == 0 and bs.totals()["haste"] == 0 and list(bs.iter_legal()) == [()]


def test_a_negative_limit_is_refused():
    with pytest.raises(ValueError, match="max_slots"):
        resolve([buff(1, "A", [(1, "STR", 5)])], max_slots=-1)


def test_a_buff_with_a_cost_stays_optional_even_when_nothing_conflicts_with_it():
    cost = buff(1, "Costly", [(1, "HPREG", -22), (2, "MANAREG", 5)])
    free = buff(2, "Free", [(1, "STR", 5)])
    bs = resolve([cost, free])
    assert ids(bs.always_on) == (2,) and ids(bs.optional) == (1,) and bs.conflicts == ()
    assert bs.totals((1,))["HPREG"] == -22 and bs.totals()["HPREG"] == 0


def test_a_buff_with_nothing_the_model_scores_is_dropped():
    inert = buff(1, "Inert", [(1, RUN_SPEED, 55)])
    bs = resolve([inert, buff(2, "Real", [(1, "STR", 5)])])
    assert ids(bs.always_on) == (2,)
    assert [(d.id, d.reason, d.by) for d in bs.dropped] == [(1, "inert", None)]


def test_a_repeated_spell_is_kept_once_and_the_first_copy_wins():
    own = Buff.from_spell(spell(7, "Same", [(1, "STR", 5)]), source="own")
    preset = Buff.from_spell(spell(7, "Same", [(1, "STR", 5)]), source="preset")
    bs = resolve([own, preset])
    assert [(b.id, b.source) for b in bs.always_on] == [(7, "own")]
    assert [(d.id, d.reason) for d in bs.dropped] == [(7, "duplicate")]


def test_equal_conflicting_buffs_leave_the_lower_id():
    first = buff(5, "First", [(1, "AC", 55), (2, "HP", 250)])
    second = buff(3, "Second", [(1, "AC", 55), (2, "HP", 250)])
    bs = resolve([first, second])
    assert ids(bs.always_on) == (3,)
    assert [(d.id, d.by) for d in bs.dropped] == [(5, 3)]


def test_a_dominated_buff_goes_even_when_its_dominator_has_other_conflicts_that_it_shares():
    a = buff(1, "A", [(1, "STR", 50), (2, "AC", 10)])
    b = buff(2, "B", [(1, "STR", 40), (2, "AC", 5)])
    c = buff(3, "C", [(2, "AC", 30), (3, "DEX", 20)])  # conflicts with both A and B, in the AC slot
    bs = resolve([a, b, c])
    assert [(d.id, d.reason, d.by) for d in bs.dropped] == [(2, "dominated", 1)]
    assert ids(bs.optional) == (1, 3) and bs.conflicts == ((1, 3),)


def test_a_dominator_is_not_always_on_when_two_compatible_buffs_could_beat_it_together():
    a = buff(1, "A", [(1, "HP", 255), (2, "AC", 75)])
    x = buff(2, "X", [(1, "HP", 250)])
    y = buff(3, "Y", [(2, "AC", 60), (5, "HP", 100)])
    assert exclusions(x, y) == ()  # X and Y stand together: HP 350 and AC 60 against A's HP 255 and AC 75
    bs = resolve([a, x, y])
    assert bs.always_on == () and ids(bs.optional) == (1, 2, 3) and bs.conflicts == ((1, 2), (1, 3))
    assert bs.dropped == ()


def test_an_always_on_buff_blocks_its_rivals_and_that_frees_a_buff_only_they_blocked():
    a = buff(1, "A", [(1, "HP", 300), (2, "AC", 100), (5, "DEX", 10)])
    x = buff(2, "X", [(1, "HP", 100), (4, "DEX", 3)])
    y = buff(3, "Y", [(2, "AC", 50)])
    z = buff(4, "Z", [(4, "DEX", 5)])  # only X stood in its way
    assert not exclusions(x, y) and exclusions(x, z) and not exclusions(a, z)
    bs = resolve([a, x, y, z])  # A beats X and Y even together (HP 100 and AC 50, DEX 3), so both are blocked
    assert ids(bs.always_on) == (1, 4) and bs.optional == () and bs.conflicts == ()
    assert [(d.id, d.reason, d.by) for d in bs.dropped] == [(2, "blocked", 1), (3, "blocked", 1)]


def test_a_rival_that_costs_something_does_not_make_a_team_worth_less():
    a = buff(1, "A", [(1, "HP", 100), (2, "AC", 20)])
    x = buff(2, "X", [(1, "HP", 50), (3, "AC", 60)])  # beats A in AC alone
    y = buff(3, "Y", [(2, "AC", -50)])  # a cost, so X and Y together total AC 10: that is no reason to trust A
    assert exclusions(a, x) and exclusions(a, y) and not exclusions(x, y)
    bs = resolve([a, x, y])
    assert bs.always_on == () and ids(bs.optional) == (1, 2, 3) and bs.conflicts == ((1, 2), (1, 3))


def ring_of_rivals(size):
    """``size`` buffs in a ring: each shares one effect slot with the next, and none beats a neighbour."""
    effect_ids = [4, 5, 6, 7, 8, 9, 10][:size]  # strength, dexterity, agility, stamina, intelligence, ...
    return [
        buff(i + 1, f"Ring {i}", [(1, effect_ids[i - 1], 10), (1, effect_ids[i], 10 + i)]) for i in range(size)
    ]


@pytest.mark.parametrize(("limit", "binds"), [(1, True), (2, False), (3, False)])
def test_the_limit_binds_exactly_when_more_buffs_can_stand_together_than_it_allows(limit, binds):
    ring = ring_of_rivals(5)  # five rivals in a ring: at most two stand together, though three cliques are needed
    rivals = {(a, b) for a, b in itertools.combinations(range(1, 6), 2) if exclusions(ring[a - 1], ring[b - 1])}
    assert rivals == {(1, 2), (2, 3), (3, 4), (4, 5), (1, 5)}
    bs = resolve(ring, max_slots=limit)
    assert (bs.cardinality == limit) is binds
    assert len(bs.optional) == 5 and bs.always_on == () and len(bs.conflicts) == 5
    assert max(len(choice) for choice in bs.iter_legal()) == min(2, limit)


def test_the_resolution_does_not_depend_on_the_order_of_the_input():
    pool = [
        buff(1, "A", [(1, "STR", 50), (2, "AC", 10)]),
        buff(2, "B", [(1, "STR", 40), (3, "AC", 30)]),
        buff(3, "C", [(1, "DEX", 5)]),
        buff(4, "D", [(1, "STR", 20)]),
        buff(5, "E", [(1, "HASTE", 130)]),
        buff(6, "F", [(4, "HASTE", 120), (5, "WIS", 4)]),
    ]
    reference = resolve(pool, max_slots=4)
    for permutation in itertools.permutations(pool, 3):
        rest = [b for b in pool if b not in permutation]
        assert resolve([*permutation, *rest], max_slots=4) == reference


def test_totals_add_the_always_on_buffs_and_the_chosen_optional_ones():
    fixed = buff(1, "Fixed", [(1, "STR", 10), (2, "FIRE", 15)])
    a = buff(2, "A", [(1, "DEX", 50), (2, "AC", 10)])
    b = buff(3, "B", [(1, "DEX", 40), (3, "AC", 30)])
    bs = resolve([fixed, a, b])
    assert bs.totals()["STR"] == 10 and bs.totals()["DEX"] == 0
    chosen = bs.totals((3,))
    assert (chosen["STR"], chosen["DEX"], chosen["AC"], chosen["sv"]["FIRE"]) == (10, 40, 30, 15)
    assert set(chosen) == {*bf.STAT_NAMES, "sv", "haste"}
    assert set(chosen["sv"]) == set(bf.SCHOOLS)
    with pytest.raises(KeyError):
        bs.totals((99,))


def test_legal_choices_respect_the_pairs_and_the_limit():
    pool = [buff(1, "A", [(1, "STR", 50), (2, "AC", 10)]), buff(2, "B", [(1, "STR", 40), (3, "AC", 30)])]
    bs = resolve(pool)
    assert sorted(bs.iter_legal()) == [(), (1,), (2,)]
    assert bs.is_legal((1,)) and not bs.is_legal((1, 2))
    three = [buff(1, "A", [(1, "STR", 5)]), buff(2, "B", [(1, "DEX", 5)]), buff(3, "C", [(1, "AGI", 5)])]
    capped = resolve(three, max_slots=2)
    assert sorted(capped.iter_legal(), key=lambda t: (len(t), t))[-1] == (2, 3)
    assert all(len(choice) <= 2 for choice in capped.iter_legal())
    assert not capped.is_legal((1, 2, 3))


def test_the_cliques_cover_every_pair_and_are_pairwise_conflicting():
    # three buffs that all want slot 1 STR, plus one more that meets only the first
    pool = [
        buff(1, "A", [(1, "STR", 50), (2, "AC", 10), (6, "WIS", 9)]),
        buff(2, "B", [(1, "STR", 40), (3, "AC", 30)]),
        buff(3, "C", [(1, "STR", 30), (4, "CHA", 60)]),
        buff(4, "D", [(6, "WIS", 4), (5, "INT", 9)]),
    ]
    bs = resolve(pool)
    assert set(bs.conflicts) == {(1, 2), (1, 3), (2, 3), (1, 4)}
    assert (1, 2, 3) in bs.cliques
    covered = set()
    for clique in bs.cliques:
        for pair in itertools.combinations(clique, 2):
            assert pair in set(bs.conflicts)
            covered.add(pair)
    assert covered == set(bs.conflicts)


# ---- the resolution is exact -----------------------------------------------------------------------------------

COMPONENT_SPAS = ("STR", "DEX", "AC", "HP", "MANAREG", "HPREG", "FIRE", "HASTE")


@st.composite
def buff_pools(draw):
    """4 to 7 random buffs: 1 to 3 effects each in 3 slots, so conflicts are common, some with costs."""
    size = draw(st.integers(min_value=4, max_value=7))
    pool = []
    for sid in range(1, size + 1):
        picked = {}
        for _ in range(draw(st.integers(min_value=1, max_value=3))):
            slot = draw(st.integers(min_value=1, max_value=3))
            kind = draw(st.sampled_from(COMPONENT_SPAS))
            low = -10 if kind in ("MANAREG", "HPREG") else 1
            value = draw(st.integers(min_value=low, max_value=60))
            picked[(slot, kind)] = 100 + abs(value) if kind == "HASTE" else value
        pool.append(buff(sid, f"Buff {sid}", [(slot, kind, value) for (slot, kind), value in picked.items()]))
    return pool


@st.composite
def monotone_objectives(draw):
    """A non-decreasing, non-concave, piecewise-linear integer objective per component: a knee, then a cap."""
    parameters = {}
    for name in bf.COMPONENTS:
        parameters[name] = (
            draw(st.integers(min_value=0, max_value=5)),   # weight
            draw(st.integers(min_value=10, max_value=200)),  # cap
            draw(st.integers(min_value=0, max_value=60)),    # knee
            draw(st.integers(min_value=1, max_value=4)),     # slope past the knee
        )  # fmt: skip

    def objective(totals):
        value = 0
        for name, (weight, cap, knee, rise) in parameters.items():
            x = min(totals[name], cap)
            value += weight * (x if x <= knee else knee + rise * (x - knee))
        return value

    return objective


def independent_totals(chosen):
    """The totals of a set of buffs, written out here and not by the engine: sums, with the best haste only."""
    totals = dict.fromkeys(bf.COMPONENTS, 0)
    for b in chosen:
        for name, number in zip(bf.COMPONENTS, b.vec, strict=True):
            if name == "HASTE":
                totals[name] = max(totals[name], number)
            else:
                totals[name] += number
    return totals


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(pool=buff_pools(), objective=monotone_objectives(), limit=st.one_of(st.none(), st.integers(1, 7)))
def test_resolving_loses_no_optimum(pool, objective, limit):
    best_of_all = None
    for size in range(len(pool) + 1):
        for subset in itertools.combinations(pool, size):
            if limit is not None and size > limit:
                continue
            if any(exclusions(a, b) for a, b in itertools.combinations(subset, 2)):
                continue
            value = objective(independent_totals(subset))
            best_of_all = value if best_of_all is None else max(best_of_all, value)
    bs = resolve(pool, max_slots=limit)
    by_id = {b.id: b for b in (*bs.always_on, *bs.optional)}
    best_resolved = None
    for choice in bs.iter_legal():
        active = [*bs.always_on, *(by_id[i] for i in choice)]
        assert limit is None or len(active) <= limit
        assert independent_totals(active) == {
            name: number for name, number in zip(bf.COMPONENTS, _vector(bs.totals(choice)), strict=True)
        }
        value = objective(independent_totals(active))
        best_resolved = value if best_resolved is None else max(best_resolved, value)
    assert best_resolved == best_of_all


def _vector(totals):
    return [*(totals[name] for name in bf.STAT_NAMES), *(totals["sv"][name] for name in bf.SCHOOLS), totals["haste"]]


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(pool=buff_pools(), limit=st.one_of(st.none(), st.integers(1, 7)), seed=st.randoms(use_true_random=False))
def test_resolving_gives_the_same_set_for_any_input_order(pool, limit, seed):
    shuffled = list(pool)
    seed.shuffle(shuffled)
    assert resolve(shuffled, max_slots=limit) == resolve(pool, max_slots=limit)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(pool=buff_pools(), limit=st.one_of(st.none(), st.integers(1, 7)))
def test_the_parts_of_a_resolution_are_consistent(pool, limit):
    bs = resolve(pool, max_slots=limit)
    by_id = {b.id: b for b in (*bs.always_on, *bs.optional)}
    always, optional = set(ids(bs.always_on)), set(ids(bs.optional))
    dropped = {d.id for d in bs.dropped}
    assert not always & optional and not always & dropped and not optional & dropped
    assert always | optional | dropped == {b.id for b in pool}
    if bs.cardinality is not None:
        assert bs.always_on == () and bs.cardinality == limit
    for a, b in bs.conflicts:
        assert a < b and a in optional and b in optional and exclusions(by_id[a], by_id[b])
    for a, b in itertools.combinations(sorted(always), 2):
        assert not exclusions(by_id[a], by_id[b])
    assert list(ids(bs.always_on)) == sorted(always) and list(ids(bs.optional)) == sorted(optional)


# ---- own buffs ---------------------------------------------------------------------------------------------------

TRIO = ("WAR", "MNK", "SHM")


def own(records, trio=TRIO, level=50, rules=RULES):
    return own_buffs(trio, level, records, rules)


def test_a_long_buff_of_a_trio_class_is_an_own_buff():
    result = own([spell(1, "Own One", [(1, "STR", 50)], classes={"SHM": 40})])
    assert [(b.id, b.name, b.source) for b in result] == [(1, "Own One", "own")]


def test_a_buff_nobody_in_the_trio_can_cast_at_the_level_is_not():
    records = [
        spell(1, "Other Class", [(1, "STR", 50)], classes={"ENC": 20}),
        spell(2, "Too High", [(1, "STR", 50)], classes={"SHM": 51}),
        spell(3, "Second Class", [(1, "STR", 50)], classes={"CLR": 10, "WAR": 50}),
    ]
    assert ids(own(records)) == (3,)
    assert ids(own(records, level=49)) == ()


def test_the_minimum_duration_is_ten_minutes_and_permanent_buffs_pass():
    records = [
        spell(1, "Short", [(1, "STR", 5)], ticks=99),
        spell(2, "Long Enough", [(1, "DEX", 5)], ticks=100),
        spell(3, "Forever", [(1, "AGI", 5)], permanent=True),
    ]
    assert ids(own(records)) == (2, 3)


def test_the_minimum_duration_comes_from_the_rules():
    strict = SimpleNamespace(get=lambda rule_id, level=50: {"buffs.min_duration_minutes": 20}[rule_id])
    records = [spell(1, "Ten Minutes", [(1, "STR", 5)], ticks=100), spell(2, "Twenty", [(1, "DEX", 5)], ticks=200)]
    assert ids(own(records, rules=strict)) == (2,)


@pytest.mark.parametrize("target", [3, 5, 6, 40, 41, 43, 51, 56])
def test_buffs_that_can_land_on_the_caster_are_own_buffs(target):
    assert ids(own([spell(1, "Lands", [(1, "STR", 5)], target=target)])) == (1,)


@pytest.mark.parametrize("target", [14, 8, 9, 11, 13, 16])
def test_pet_only_and_other_targets_are_not(target):
    assert own([spell(1, "Elsewhere", [(1, "STR", 5)], target=target)]) == []


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("Fearless Discipline", "discipline"),
        ("Item Benefit: Invented Song", "item-benefit"),
        ("Illusion: Invented Beast", "illusion-spell"),
        ("Temperance", "temperance"),
        ("Blessing of Temperance", "temperance"),
    ],
)
def test_disciplines_item_benefits_illusion_spells_and_the_temperance_line_are_left_out(name, reason):
    record = spell(1, name, [(1, "STR", 5)])
    assert own([record]) == []
    assert bf.exclusion_reason(record, TRIO, 50, 10) == reason


def test_a_rooting_form_is_left_out_and_a_free_form_is_kept_with_its_badge():
    root = spell(1, "Rooted Shape", [(1, ILLUSION, 143), (2, ROOT, -10000), (3, "FIRE", -10)], classes={"SHM": 6})
    free = spell(2, "Free Shape", [(1, ILLUSION, 796), (2, RUN_SPEED, 55), (3, "ATK", 30)], classes={"SHM": 20})
    result = own([root, free])
    assert ids(result) == (2,) and result[0].illusion is True
    assert bf.exclusion_reason(root, TRIO, 50, 10) == "root"


def test_a_buff_the_model_does_not_score_or_cannot_value_is_left_out():
    inert = spell(1, "Fleet", [(1, RUN_SPEED, 55)])
    unknown = spell(2, "Odd Formula", [(1, "STR", 5)])
    unknown["effects"][0]["value"] = None
    assert own([inert, unknown]) == []
    assert bf.exclusion_reason(inert, TRIO, 50, 10) == "inert"
    assert bf.exclusion_reason(unknown, TRIO, 50, 10) == "unknown-formula"


def test_exclusion_reason_is_none_for_a_kept_buff_and_names_the_first_failure_otherwise():
    assert bf.exclusion_reason(spell(1, "Fine", [(1, "STR", 5)]), TRIO, 50, 10) is None
    assert bf.exclusion_reason(spell(2, "Wrong Class", [(1, "STR", 5)], classes={"ENC": 5}), TRIO, 50, 10) == "class"
    assert bf.exclusion_reason(spell(3, "Pet", [(1, "STR", 5)], target=14), TRIO, 50, 10) == "target"
    assert bf.exclusion_reason(spell(4, "Brief", [(1, "STR", 5)], ticks=10), TRIO, 50, 10) == "duration"


def test_a_class_code_that_does_not_exist_is_refused():
    with pytest.raises(ValueError, match="class"):
        own([], trio=("WAR", "MNK", "XXX"))


def test_the_spells_can_be_given_as_the_derived_file_or_as_a_bare_list():
    records = [spell(1, "Own One", [(1, "STR", 50)])]
    wrapped = {"level": 50, "unknown_formulas": {}, "spells": records}
    assert ids(own(wrapped)) == ids(own(records)) == (1,)
    with pytest.raises(ValueError, match="level"):
        own(wrapped, level=55)


def test_own_buffs_are_listed_by_spell_id():
    records = [spell(30, "C", [(1, "STR", 5)]), spell(10, "A", [(1, "DEX", 5)]), spell(20, "B", [(1, "AGI", 5)])]
    assert ids(own(records)) == (10, 20, 30)


# ---- the common group preset -------------------------------------------------------------------------------------

THIRTEEN = [
    "Talisman of Altuna", "Strength", "Dexterity", "Agility", "Stamina", "Infusion of Spirit", "Alacrity",
    "Spirit of Bih`Li", "Chloroplast", "Symbol of Naltron", "Resolution", "Shield of Words", "Clarity",
]  # fmt: skip


def preset_records():
    return [
        spell(100 + position, name, [(position + 1, 7 + position % 3, 10 + position)], classes={"SHM": 10 + position})
        for position, name in enumerate(THIRTEEN)
    ]


def test_the_preset_names_are_the_thirteen_common_group_buffs():
    assert list(bf.PRESET_NAMES) == THIRTEEN


def test_the_preset_is_found_by_exact_name_and_returned_in_preset_order():
    records = [*reversed(preset_records()), spell(900, "Not In It", [(1, "STR", 5)])]
    result = group_preset(records)
    assert [b.name for b in result] == THIRTEEN
    assert all(b.source == "preset" for b in result)


def test_a_name_missing_from_the_spell_file_is_an_error_that_names_it():
    records = [r for r in preset_records() if r["name"] != "Clarity"]
    with pytest.raises(ValueError, match="Clarity"):
        group_preset(records)


def test_a_name_that_differs_only_in_the_backtick_is_not_found():
    records = preset_records()
    next(r for r in records if r["name"] == "Spirit of Bih`Li")["name"] = "Spirit of Bih'Li"
    with pytest.raises(ValueError, match="Bih"):
        group_preset(records)


def test_a_preset_spell_the_group_could_not_cast_yet_is_skipped():
    records = preset_records()
    records[-1]["classes"] = {"ENC": 26}
    assert [b.name for b in group_preset(records, level=25)] == THIRTEEN[:-1]
    assert len(group_preset(records, level=50)) == 13


def test_the_preset_takes_the_level_of_a_wrapped_file_when_none_is_given():
    records = preset_records()
    records[-1]["classes"] = {"ENC": 26}
    assert len(group_preset({"level": 25, "spells": records})) == 12
    assert len(group_preset({"level": 50, "spells": records})) == 13
    assert len(group_preset({"level": 25, "spells": records}, level=50)) == 13


def test_a_trio_that_casts_a_preset_buff_itself_counts_it_once_as_its_own():
    records = preset_records()
    merged = resolve([*own(records, trio=("SHM", "WAR", "MNK")), *group_preset(records)])
    assert len(merged.always_on) == 13 and {b.source for b in merged.always_on} == {"own"}
    assert [d.reason for d in merged.dropped] == ["duplicate"] * 13


def test_a_trio_that_cannot_cast_them_gets_the_preset_as_group_buffs():
    records = preset_records()
    assert own(records, trio=("WAR", "MNK", "PAL")) == []
    merged = resolve(group_preset(records))
    assert len(merged.always_on) == 13 and {b.source for b in merged.always_on} == {"preset"}


# ---- the committed client files ------------------------------------------------------------------------------------


def spells_file(level):
    return json.loads((DERIVED / f"spells-l{level}.json").read_text(encoding="utf-8"))


def by_name(data, name):
    (found,) = [r for r in data["spells"] if r["name"] == name]
    return found


@pytest.fixture(scope="module")
def l50():
    return spells_file(50)


@pytest.fixture(scope="module")
def l55():
    return spells_file(55)


def test_a_shaman_trios_own_buffs_include_talisman_of_altuna(l50):
    names = {b.name for b in own_buffs(("PAL", "MNK", "SHM"), 50, l50, RULES)}
    assert "Talisman of Altuna" in names


def test_a_clerics_armor_of_the_faithful_excludes_talisman_of_altuna_and_wins_by_value(l50):
    altuna = Buff.from_spell(by_name(l50, "Talisman of Altuna"))
    faithful = Buff.from_spell(by_name(l50, "Armor of the Faithful"))
    assert exclusions(faithful, altuna) == ("slot1/spa69",)
    bs = resolve([altuna, faithful])
    assert ids(bs.always_on) == (faithful.id,)
    assert [(d.id, d.reason, d.by) for d in bs.dropped] == [(altuna.id, "dominated", faithful.id)]


def test_a_cleric_trio_merged_with_the_group_preset_loses_the_groups_talisman(l50):
    mine = own_buffs(("CLR", "WAR", "MNK"), 50, l50, RULES)
    merged = resolve([*mine, *group_preset(l50)], RULES)
    chosen = {b.name for b in (*merged.always_on, *merged.optional)}
    assert "Armor of the Faithful" in chosen and "Talisman of Altuna" not in chosen
    assert any(d.name == "Talisman of Altuna" for d in merged.dropped)


@pytest.mark.parametrize("level", [50, 55])
def test_all_thirteen_preset_names_are_in_the_client_file_and_stack_with_each_other(level):
    data = spells_file(level)
    preset = group_preset(data)
    assert [b.name for b in preset] == THIRTEEN
    for a, b in itertools.combinations(preset, 2):
        assert exclusions(a, b) == (), (a.name, b.name)
    totals = resolve(preset).totals()
    assert totals["STR"] == 67 + 50 and totals["haste"] == 40 and totals["HP"] == 250 + 250 + 525


SAMPLE_TRIOS = [
    ("PAL", "MNK", "BER"), ("SHD", "CLR", "SHM"), ("WIZ", "MAG", "ENC"), ("WAR", "CLR", "SHM"), ("BRD", "RNG", "BST"),
]  # fmt: skip


@pytest.mark.parametrize("level", [50, 55])
@pytest.mark.parametrize("trio", SAMPLE_TRIOS)
def test_the_sample_trios_resolve_to_a_consistent_deterministic_set(trio, level):
    data = spells_file(level)
    first = resolve(own_buffs(trio, level, data, RULES), RULES)
    second = resolve(list(reversed(own_buffs(trio, level, data, RULES))), RULES)
    assert first == second
    assert isinstance(first, BuffSet)
    for buff_ in (*first.always_on, *first.optional):
        assert any(buff_.vec) and buff_.source == "own"
        assert buff_.illusion == any(spa == 58 for _, spa, _ in buff_.effects)
    assert first.cardinality in (None, RULES.get("buffs.max_slots"))
    if first.cardinality is None:  # then the limit can never cut: the most that can stand together fits under it
        most = max(len(choice) for choice in first.iter_legal())
        assert len(first.always_on) + most <= RULES.get("buffs.max_slots")


def test_the_cardinality_limit_binds_for_a_trio_with_both_cleric_and_shaman_buffs(l50):
    bs = resolve(own_buffs(("SHD", "CLR", "SHM"), 50, l50, RULES), RULES)
    assert bs.cardinality == 15 and bs.always_on == ()
    assert len(bs.optional) > 15


def test_a_trio_with_few_rival_buffs_has_them_always_on_except_the_ones_with_a_cost(l50):
    bs = resolve(own_buffs(("PAL", "MNK", "BER"), 50, l50, RULES), RULES)
    assert bs.cardinality is None and bs.conflicts == () and len(bs.always_on) >= 5
    assert all(min(b.vec) >= 0 for b in bs.always_on)
    assert [b.name for b in bs.optional] == ["Divine Purpose"] and min(bs.optional[0].vec) < 0  # mana regen -3


@pytest.mark.parametrize("level", [50, 55])
def test_no_long_buff_in_the_client_files_carries_the_other_haste_effects(level):
    # The engine counts the attack speed effect (11) only; this fails loudly if a long buff ever has haste 98 or 119.
    for record in spells_file(level)["spells"]:
        long_lasting = record["permanent"] or record["duration_ticks"] * 6 >= 600
        assert not (long_lasting and any(effect["spa"] in (98, 119) for effect in record["effects"])), record["name"]
