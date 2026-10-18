"""Tests for the Enchanter and raid buff presets of ``trioforge.model.buffs``.

``enchanter_preset(spells, level)`` is the "Enchanter in group" haste line: the best haste an Enchanter can cast on
somebody else at the level, as one buff. ``raid_preset(spells, level)`` is the full raid: the 13 common group buffs plus
every long buff that some class can cast on others. Both feed ``resolve`` next to the trio's own buffs, with the
15-slot row, and the raid set holds everything the group set holds, so the best kit can never be worth less in the raid.

The unit tests use synthetic spell records under invented names (the shape of ``derived/client/spells-l50.json``). The
integration tests read the committed client files, and the last one solves real catalog pools with the real solver for
20 random trios.
"""

import copy
import itertools
import json
import random
from pathlib import Path

import pytest

from trioforge.classes import CLASS_CODES
from trioforge.model import buffs as bf
from trioforge.model.buffs import Buff, enchanter_preset, group_preset, own_buffs, raid_preset, resolve
from trioforge.model.items import at_tier
from trioforge.model.profile import make_profile
from trioforge.model.tables import load as load_tables
from trioforge.precompute import grid
from trioforge.rules import Rules
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.prune import prune
from trioforge.solver.solve import solve

REPO_ROOT = Path(__file__).resolve().parents[2]
DERIVED = REPO_ROOT / "derived" / "client"
TABLES = load_tables()
RULES = TABLES.rules
RAW_RULES = json.loads((REPO_ROOT / "rules" / "rules.json").read_text(encoding="utf-8"))

SPA = {"STR": 4, "AC": 1, "HP": 69, "HASTE": 11, "MANAREG": 15, "DEX": 5, "STA": 7, "RUN": 3}
THIRTEEN = list(bf.PRESET_NAMES)


# ---- synthetic records ---------------------------------------------------------------------------------------------


def spell(sid, name, effects, *, classes, target=5, ticks=300, permanent=False):
    """A spell record in the shape of the derived file; ``effects`` is a list of (slot, what, value)."""
    return {
        "id": sid,
        "name": name,
        "classes": dict(classes),
        "target": target,
        "duration_ticks": None if permanent else ticks,
        "permanent": permanent,
        "effects": [
            {"slot": slot, "spa": SPA[what], "name": what, "base": value, "limit": 0, "formula": 100, "max": value,
             "value": value}
            for slot, what, value in effects
        ],  # fmt: skip
        "stacking": [],
    }


def haste(sid, name, percent, *, classes=None, **kwargs):
    """A spell whose only effect is attack speed ``percent`` over 100 (the file writes 140 for 40%)."""
    return spell(sid, name, [(1, "HASTE", 100 + percent)], classes=classes or {"ENC": 30}, **kwargs)


def preset_records():
    """The thirteen group buffs as plain stat spells that a Shaman casts at level 10 and up."""
    return [
        spell(100 + position, name, [(1, "STR", 10 + position)], classes={"SHM": 10 + position})
        for position, name in enumerate(THIRTEEN)
    ]


def names(buffs):
    return [b.name for b in buffs]


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


# ---- enchanter_preset: the haste line ------------------------------------------------------------------------------


def test_the_enchanter_line_at_level_50_is_the_60_percent_haste_of_the_client_file(l50):
    record = by_name(l50, "Swift Like the Wind")
    assert record["classes"] == {"ENC": 47}
    assert [e["value"] for e in record["effects"] if e["spa"] == 11] == [160]
    (found,) = enchanter_preset(l50, 50)
    assert (found.id, found.name, found.haste, found.source) == (record["id"], "Swift Like the Wind", 60, "preset")
    assert found == Buff.from_spell(record, source="preset")


@pytest.mark.parametrize(
    ("level", "name", "percent"),
    [
        (15, "Quickness", 30),
        (20, "Quickness", 30),
        (21, "Alacrity", 40),
        (38, "Alacrity", 40),
        (39, "Celerity", 50),
        (46, "Celerity", 50),
        (47, "Swift Like the Wind", 60),
        (49, "Swift Like the Wind", 60),
        (50, "Swift Like the Wind", 60),
    ],
)
def test_the_line_follows_the_class_levels_of_the_client_file_at_each_boundary(l50, level, name, percent):
    (found,) = enchanter_preset(l50, level)
    assert (found.name, found.haste) == (name, percent)


@pytest.mark.parametrize("level", [1, 5, 14])
def test_a_level_below_the_first_rank_has_no_enchanter_haste(l50, level):
    assert enchanter_preset(l50, level) == []


def test_at_level_55_the_line_ends_in_the_higher_rank_of_the_other_file(l55):
    assert [(b.name, b.haste) for b in enchanter_preset(l55, 52)] == [("Swift Like the Wind", 60)]
    assert [(b.name, b.haste) for b in enchanter_preset(l55, 53)] == [("Aanya's Quickening", 64)]
    assert [(b.name, b.haste) for b in enchanter_preset(l55, 55)] == [("Aanya's Quickening", 64)]


def test_the_best_haste_wins_whatever_the_order_of_the_records():
    records = [haste(5, "Beta", 30), haste(3, "Alpha", 45), haste(9, "Gamma", 20)]
    assert names(enchanter_preset(records, 50)) == ["Alpha"]
    assert names(enchanter_preset(list(reversed(records)), 50)) == ["Alpha"]


def test_equal_hastes_go_to_the_lower_spell_id():
    records = [haste(8, "Later", 40), haste(2, "Earlier", 40)]
    assert names(enchanter_preset(records, 50)) == ["Earlier"]


@pytest.mark.parametrize(
    "rival",
    [
        haste(1, "Shaman Only", 70, classes={"SHM": 20}),
        haste(1, "Self Only", 70, target=6),
        haste(1, "Pet Only", 70, target=14),
        haste(1, "Too Short", 70, ticks=50),
        haste(1, "A Slow", -30),
        haste(1, "Level 60", 70, classes={"ENC": 60}),
    ],
)
def test_only_a_long_haste_an_enchanter_can_cast_on_others_by_the_level_counts(rival):
    records = [haste(2, "The One", 40), rival]
    assert names(enchanter_preset(records, 50)) == ["The One"]
    assert enchanter_preset([rival], 50) == []


def test_a_permanent_haste_counts_as_long():
    assert names(enchanter_preset([haste(1, "Endless", 40, permanent=True)], 50)) == ["Endless"]


def test_a_spell_with_other_effects_than_haste_keeps_them_in_its_vector():
    record = spell(7, "Both", [(1, "HASTE", 150), (2, "STR", 12)], classes={"ENC": 20}, target=51)
    (found,) = enchanter_preset([record], 50)
    assert found.haste == 50 and found.stats["STR"] == 12


def test_the_file_may_be_the_wrapped_document_or_a_bare_list(l50):
    assert enchanter_preset(l50["spells"], 50) == enchanter_preset(l50, 50)


@pytest.mark.parametrize("level", [0, -1, 1.5, "50", True, None])
def test_a_level_that_is_not_a_whole_number_from_1_is_refused(level):
    with pytest.raises(ValueError, match="level"):
        enchanter_preset([haste(1, "Any", 40)], level)
    with pytest.raises(ValueError, match="level"):
        raid_preset(preset_records(), level)


# ---- raid_preset: everything long that a class can cast on others -------------------------------------------------


def raid_records():
    long_cleric = spell(300, "Long Cleric Ward", [(1, "HP", 200)], classes={"CLR": 30})
    return [
        *reversed(preset_records()),
        long_cleric,
        spell(301, "Druid Skin", [(1, "AC", 20)], classes={"DRU": 25}, target=3),
        spell(302, "Self Only Long", [(1, "STR", 30)], classes={"WAR": 10}, target=6),
        spell(303, "Short Buff", [(1, "STR", 30)], classes={"CLR": 10}, ticks=40),
        spell(304, "Pet Buff", [(1, "STR", 30)], classes={"MAG": 10}, target=14),
        spell(305, "Illusion: Imp", [(1, "STR", 30)], classes={"MAG": 10}),
        spell(306, "Some Discipline", [(1, "STR", 30)], classes={"WAR": 10}),
        spell(307, "Too High", [(1, "STR", 30)], classes={"CLR": 51}),
        spell(308, "Does Nothing", [(1, "RUN", 40)], classes={"CLR": 10}),
        spell(309, "Item Benefit: Fake", [(1, "STR", 30)], classes={"BRD": 1}),
        spell(310, "Group Buff", [(1, "DEX", 9)], classes={"PAL": 40}, target=41),
        spell(299, "Endless Ward", [(1, "STA", 9)], classes={"RNG": 20}, permanent=True),
    ]  # fmt: skip


def test_the_raid_is_the_group_buffs_then_every_long_buff_castable_on_others_by_id():
    result = raid_preset(raid_records(), 50)
    assert names(result)[:13] == THIRTEEN
    assert names(result)[13:] == ["Endless Ward", "Long Cleric Ward", "Druid Skin", "Group Buff"]
    assert {b.source for b in result} == {"preset"}
    assert len({b.id for b in result}) == len(result)


@pytest.mark.parametrize(
    "left_out",
    ["Self Only Long", "Short Buff", "Pet Buff", "Illusion: Imp", "Some Discipline", "Too High", "Does Nothing",
     "Item Benefit: Fake"],
)  # fmt: skip
def test_the_raid_leaves_out_what_the_group_cannot_use(left_out):
    assert left_out not in names(raid_preset(raid_records(), 50))


def test_the_class_level_gates_the_raid_like_the_group():
    result = raid_preset(raid_records(), 29)
    assert "Long Cleric Ward" not in names(result) and "Druid Skin" in names(result)
    assert names(result)[: len(group_preset(raid_records(), level=29))] == names(group_preset(raid_records(), level=29))


def test_the_raid_needs_the_whole_group_preset_in_the_file_like_the_group_does():
    records = [r for r in raid_records() if r["name"] != "Clarity"]
    with pytest.raises(ValueError, match="Clarity"):
        raid_preset(records, 50)


def test_the_raid_is_the_same_whatever_the_order_of_the_records():
    forward = raid_preset(raid_records(), 50)
    assert raid_preset(list(reversed(raid_records())), 50) == forward


def with_min_minutes(minutes):
    data = copy.deepcopy(RAW_RULES)
    for rule in data["rules"]:
        if rule["id"] == "buffs.min_duration_minutes":
            rule["value"] = minutes
    return Rules(data)


def test_the_length_that_counts_as_long_comes_from_the_rules():
    records = raid_records()
    twelve_minutes = spell(311, "Twelve Minutes", [(1, "STR", 7)], classes={"CLR": 20}, ticks=120)
    assert "Twelve Minutes" in names(raid_preset([*records, twelve_minutes], 50, rules=with_min_minutes(10)))
    assert "Twelve Minutes" not in names(raid_preset([*records, twelve_minutes], 50, rules=with_min_minutes(15)))
    assert "Twelve Minutes" in names(raid_preset([*records, twelve_minutes], 50, rules=with_min_minutes(2)))
    assert "Short Buff" in names(raid_preset(records, 50, rules=with_min_minutes(2)))
    slow_burn = [haste(1, "Slow Burn", 40, ticks=120)]
    assert names(enchanter_preset(slow_burn, 50, rules=with_min_minutes(15))) == []
    assert names(enchanter_preset(slow_burn, 50, rules=with_min_minutes(10))) == ["Slow Burn"]


def test_without_rules_the_length_is_the_value_of_the_rules_file():
    assert bf.DEFAULT_LONG_MINUTES == RULES.get("buffs.min_duration_minutes")
    records = raid_records()
    assert raid_preset(records, 50) == raid_preset(records, 50, rules=RULES)


def test_castable_on_others_is_every_target_a_buff_can_land_on_except_self():
    assert bf.OTHER_TARGETS == bf.SELF_TARGETS - {6}
    assert 6 in bf.SELF_TARGETS and 14 not in bf.SELF_TARGETS


# ---- the committed client files ------------------------------------------------------------------------------------


@pytest.mark.parametrize("level", [50, 55])
def test_the_raid_holds_the_group_buffs_and_the_enchanter_line(level):
    data = spells_file(level)
    raid_ids = [b.id for b in raid_preset(data, level)]
    assert len(raid_ids) == len(set(raid_ids))
    assert {b.id for b in group_preset(data, level=level)} <= set(raid_ids)
    assert {b.id for b in enchanter_preset(data, level)} <= set(raid_ids)
    assert raid_ids[:13] == [b.id for b in group_preset(data, level=level)]


@pytest.mark.parametrize("level", [50, 55])
def test_every_extra_raid_buff_is_long_and_castable_on_others_by_some_class(level):
    data = spells_file(level)
    records = {r["id"]: r for r in data["spells"]}
    taken = {b.id for b in group_preset(data, level=level)}
    extras = [b for b in raid_preset(data, level) if b.id not in taken]
    assert 80 <= len(extras) <= 140
    for buff in extras:
        record = records[buff.id]
        assert record["target"] in bf.OTHER_TARGETS
        assert record["permanent"] or record["duration_ticks"] * 6 >= 600
        assert any(0 < got <= level for got in record["classes"].values())
        assert any(buff.vec)


def test_the_raid_has_no_self_only_buff_of_the_client_file(l50):
    selfish = {r["id"] for r in l50["spells"] if r["target"] == 6}
    assert selfish and not selfish & {b.id for b in raid_preset(l50, 50)}


SAMPLE_TRIOS = [("PAL", "MNK", "BER"), ("SHD", "CLR", "SHM"), ("WIZ", "MAG", "ENC"), ("WAR", "ROG", "BST")]


@pytest.mark.parametrize("level", [50, 55])
@pytest.mark.parametrize("trio", SAMPLE_TRIOS)
def test_the_raid_resolves_to_30_to_40_optional_buffs_with_the_slot_row_binding(trio, level):
    data = spells_file(level)
    merged = resolve([*own_buffs(trio, level, data, RULES), *raid_preset(data, level)], RULES)
    assert merged.cardinality == RULES.get("buffs.max_slots") == 15
    assert merged.always_on == ()
    assert 30 <= len(merged.optional) <= 45


@pytest.mark.parametrize("trio", SAMPLE_TRIOS)
def test_the_enchanter_line_lifts_the_best_spell_haste_of_the_group_set(trio, l50):
    own = own_buffs(trio, 50, l50, RULES)
    group = resolve([*own, *group_preset(l50)], RULES)
    with_enchanter = resolve([*own, *group_preset(l50), *enchanter_preset(l50, 50)], RULES)

    def best(buffset):
        return max(b.haste for b in (*buffset.always_on, *buffset.optional))

    assert best(with_enchanter) >= best(group)
    if "ENC" not in trio and "BRD" not in trio:  # nobody of the trio casts the 60% line itself
        assert (best(group), best(with_enchanter)) == (40, 60)


# ---- the raid never makes the best kit worse ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def catalog():
    document = json.loads((REPO_ROOT / "derived" / "catalog.json").read_text(encoding="utf-8"))
    return document["items"]


def best_values(trio, pool, buffsets):
    """The optimal F of one trio and one pool under each named buff set (the same pool, race, role and setup)."""
    race = grid.race_order(trio, TABLES)[0][0]
    options = BuildOptions()
    values = {}
    for key, buffset in buffsets.items():
        profile = make_profile(race, trio, 50, "balanced", buffset, None, TABLES)
        setup = make_profile(race, trio, 50, "balanced", None, None, TABLES).setups[0]
        items = [at_tier(item, 4, RULES) for item in pool]
        kept = prune(items, profile, 4, setup, buffset, options)
        solution = solve(build_milp(profile, kept, setup, buffset, options))
        assert solution.status == "optimal", (trio, key)
        values[key] = solution.F
    return values


def test_f_of_the_raid_is_at_least_f_of_the_group_on_20_random_trios(l50, catalog):
    rng = random.Random(20261014)
    trios = rng.sample(list(itertools.combinations(CLASS_CODES, 3)), 20)
    strictly_better = 0
    for trio in trios:
        selection = grid.select_items(catalog, trio)
        pool_all = grid.pool_dicts(selection, "wiki")
        pool = rng.sample(pool_all, min(160, len(pool_all)))
        own = own_buffs(trio, 50, l50, RULES)
        group, enchanter = group_preset(l50), enchanter_preset(l50, 50)
        buffsets = {
            "own": resolve(own, RULES),
            "group": resolve([*own, *group], RULES),
            "group+enchanter": resolve([*own, *group, *enchanter], RULES),
            "raid": resolve([*own, *raid_preset(l50, 50)], RULES),
        }
        assert buffsets["raid"].cardinality == 15 and buffsets["group"].cardinality in (None, 15)
        f = best_values(trio, pool, buffsets)
        slack = 1e-9 * max(1.0, abs(f["raid"]))
        assert f["own"] <= f["group"] + slack, (trio, f)
        assert f["group"] <= f["group+enchanter"] + slack, (trio, f)
        assert f["group+enchanter"] <= f["raid"] + slack, (trio, f)
        strictly_better += f["raid"] > f["group"] + 1e-6
    assert strictly_better >= 15  # the property is not vacuous: the extra buffs are worth something


def test_a_raid_with_a_tighter_slot_row_can_fall_below_the_group_so_the_check_has_teeth(l50, catalog):
    trio = ("PAL", "MNK", "BER")
    rng = random.Random(5)
    pool = rng.sample(grid.pool_dicts(grid.select_items(catalog, trio), "wiki"), 160)
    own = own_buffs(trio, 50, l50, RULES)
    group = resolve([*own, *group_preset(l50)], RULES)
    squeezed = resolve([*own, *raid_preset(l50, 50)], RULES, max_slots=3)
    f = best_values(trio, pool, {"group": group, "squeezed": squeezed})
    assert f["squeezed"] < f["group"] - 1e-6
