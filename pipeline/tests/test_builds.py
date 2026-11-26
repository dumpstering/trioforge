"""The builds: Tank, Shield caster, Melee damage, Archer, Caster tank and Caster replace the roles of the earlier release, and Balanced is gone.

What is held here, in the order of the work order of 2026-11-18:

* which builds a trio is offered, and which weapon setups each build has (by rule, for all 560 trios, with a pool and with none);
* the build a trio's page opens on (every trio has one, and it is always one the trio is offered), and the default race rule (close races);
* ``haste.assume_spell``: a kit is chosen on gear haste alone, and with the rule true the profile is what the code before the builds made;
* the weapon damage factor of each build (one mechanism for every build: a factor of 0 chooses the hands on stats and armour class alone);
* no Balanced anywhere in a results folder, and an old results folder is refused, by the precompute's resume and by the site's reader, with a clear message.

Every class list below is written out here on purpose, so these tests do not trust the module they check. Every item here is invented.
"""

from __future__ import annotations

import copy
import itertools
import re
import json
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from solver_helpers import make_item
from trioforge.classes import CLASS_CODES
from trioforge.data.jsonio import load_strict
from trioforge.export import browser
from trioforge.model import buffs as buff_model
from trioforge.model import roles, weapons
from trioforge.model.items import WeaponVec
from trioforge.model.profile import make_profile
from trioforge.model.tables import load
from trioforge.rules import Rules
from trioforge.rules import load as load_rules
from trioforge.solver.haste import solve_scenario
from trioforge.solver.model import BuildOptions

REPO = Path(__file__).resolve().parents[2]
TABLES = load()
RULES = load_rules()
RAW = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))
SPELLS = load_strict(REPO / "derived" / "client" / "spells-l50.json")
TRIOS = list(itertools.combinations(CLASS_CODES, 3))

TK = {"WAR", "PAL", "SHD"}
SPELL = {"CLR", "DRU", "SHM", "WIZ", "NEC", "MAG", "ENC"}
MELEE = {"WAR", "PAL", "SHD", "MNK", "ROG", "BER", "BRD", "BST", "RNG"}
PETC = {"MAG", "NEC", "BST", "ENC"}
BUILDS = ("tank", "shield", "melee", "ranged", "castertank", "caster")
LABELS = {"tank": "Tank", "shield": "Shield caster", "melee": "Melee damage", "ranged": "Archer", "castertank": "Caster tank", "caster": "Caster"}
#: the count of trios of the 560 that are offered each build (the Archer build with a bow in the pool)
OFFERED_COUNTS = {"tank": 274, "shield": 210, "melee": 525, "ranged": 105, "castertank": 161, "caster": 224}
#: the count of trios whose page opens on each build, when the Archer build is offered to every Ranger, and when it is offered to none (no bow in the pool)
OPENING_COUNTS = {"tank": 226, "shield": 48, "ranged": 66, "melee": 101, "castertank": 22, "caster": 97}
OPENING_COUNTS_NO_BOW = {"tank": 226, "shield": 48, "melee": 146, "castertank": 28, "caster": 112}


def rules_with(**changes):
    """The real rules with the value of some rules replaced (``rules_with(**{"roles.weapon_factor": ...})``)."""
    data = copy.deepcopy(RAW)
    seen = set()
    for rule in data["rules"]:
        if rule["id"] in changes:
            rule["value"] = changes[rule["id"]]
            seen.add(rule["id"])
    assert seen == set(changes), "a rule id that the real file does not have"
    return Rules(data)


def offered(trio):
    """The builds of the work order, written out again: item 2 of it."""
    members = set(trio)
    tank, spell, melee = members & TK, members & SPELL, members & MELEE
    found = []
    if tank:
        found.append("tank")
    if tank and spell:
        found.append("shield")
    if melee:
        found.append("melee")
    if "RNG" in members:
        found.append("ranged")
    if not tank and len(spell) >= 2:
        found.append("castertank")
    if spell and (not melee or len(spell) >= 2):
        found.append("caster")
    return found


# ---- the vocabulary and the class groups -------------------------------------------------------------------------------------


def test_the_builds_are_these_six_in_this_order_and_balanced_is_gone():
    assert roles.ROLES == BUILDS
    assert weapons.ROLES == roles.ROLES
    assert "balanced" not in roles.ROLES and roles.REMOVED_ROLES == {"balanced"}
    assert set(roles.TEMPLATES) == set(BUILDS) - {"ranged"}  # the Archer is the Melee template with factors


def test_the_class_groups_are_the_ones_of_the_design():
    assert roles.TANK_CLASSES == TK
    assert roles.CASTER_CLASSES == SPELL
    assert roles.MELEE_CLASSES == MELEE
    assert roles.PET_CLASSES == PETC
    assert MELEE | SPELL == set(CLASS_CODES) and not MELEE & SPELL


# ---- which builds a trio is offered -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trio", "expected"),
    [
        (("PAL", "MNK", "BER"), ["tank", "melee"]),
        (("WIZ", "MAG", "ENC"), ["castertank", "caster"]),
        (("SHD", "CLR", "SHM"), ["tank", "shield", "melee", "caster"]),
        (("MNK", "ROG", "BER"), ["melee"]),  # one melee build only: no caster, no tank class
        (("BRD", "RNG", "BST"), ["melee", "ranged"]),
        (("CLR", "MNK", "ROG"), ["melee"]),  # one caster beside melee classes: no Caster build (something else in front is a melee class)
        (("CLR", "DRU", "SHM"), ["castertank", "caster"]),
        (("WAR", "PAL", "SHD"), ["tank", "melee"]),  # a tank class and no caster: no Shield caster
        (("WAR", "CLR", "DRU"), ["tank", "shield", "melee", "caster"]),
        (("WAR", "CLR", "MNK"), ["tank", "shield", "melee"]),
        (("RNG", "SHM", "CLR"), ["melee", "ranged", "castertank", "caster"]),
        (("WAR", "RNG", "ROG"), ["tank", "melee", "ranged"]),
        (("WIZ", "NEC", "MNK"), ["melee", "castertank", "caster"]),
    ],
)
def test_the_builds_offered_to_the_examples(trio, expected):
    assert roles.roles_for(trio, bow=None) == expected
    assert roles.roles_for(trio, bow=True) == expected
    assert roles.roles_for(trio, bow=False) == [role for role in expected if role != "ranged"]  # (no bow in the pool: no Archer)
    assert roles.roles_for(trio) == roles.roles_for(trio, bow=False)  # (and a bow is never assumed)


def test_every_trio_is_offered_at_least_one_build_and_at_most_four_and_they_are_the_rules_of_the_work_order():
    assert len(TRIOS) == 560
    counts = Counter()
    for trio in TRIOS:
        got = roles.roles_for(trio, bow=None)
        assert got == offered(trio), trio
        assert 1 <= len(got) <= 4, (trio, got)  # (the Archer counted)
        assert got == [role for role in BUILDS if role in got]  # in the fixed order
        counts.update(got)
    assert dict(counts) == OFFERED_COUNTS
    assert sum(1 for trio in TRIOS if not set(trio) & MELEE and not set(trio) & SPELL) == 0  # (every class is one or the other)


def test_the_order_of_the_trio_does_not_change_its_builds():
    assert roles.roles_for(("BER", "MNK", "PAL")) == roles.roles_for(["PAL", "MNK", "BER"])


# ---- the weapon setups of each build ----------------------------------------------------------------------------------------


def invented_pool():
    shield = make_item("it-shield", {"SECONDARY"}, stats={"AC": 10}, shield=True)
    bow = make_item("it-bow", {"RANGE"}, classes=("WAR", "PAL", "SHD", "RNG", "ROG"), weapon=WeaponVec("Archery", 20, 40, None, False))
    return shield, bow


def test_the_setups_of_each_build_follow_the_work_order():
    shield, bow = invented_pool()
    both = [shield, bow]
    expect = {
        ("WAR", "CLR", "DRU"): {"tank": ["1h-shield", "2h", "dw"], "shield": ["1h-shield", "stick"], "melee": ["2h", "dw"], "caster": ["stick", "1h-shield"]},  # (the Caster lists the stick first: the first setup wins a tie)
        ("DRU", "WIZ", "ENC"): {"castertank": ["1h-shield", "stick"], "caster": ["stick", "1h-shield"]},
    }
    for trio, by_build in expect.items():
        for build, setups in by_build.items():
            assert weapons.setups_for(trio, build, TABLES, items=[shield]) == setups, (trio, build)
            assert weapons.setups_for(trio, build, TABLES, items=both)[: len(setups)] == setups, (trio, build)
    # the bow is the last setup of Tank and Melee damage, as it is today, and no casting build has it
    trio = ("WAR", "CLR", "DRU")
    assert weapons.setups_for(trio, "tank", TABLES, items=both) == ["1h-shield", "2h", "dw", "ranged"]
    assert weapons.setups_for(trio, "melee", TABLES, items=both) == ["2h", "dw", "ranged"]
    for build in ("shield", "caster"):
        assert "ranged" not in weapons.setups_for(trio, build, TABLES, items=both)
    assert weapons.setups_for(("RNG", "SHM", "CLR"), "ranged", TABLES, items=both) == ["ranged"]
    assert weapons.setups_for(("RNG", "SHM", "CLR"), "ranged", TABLES, items=[shield]) == []  # (no bow in the pool: the Archer has no setup)
    assert weapons.setups_for(("RNG", "SHM", "CLR"), "ranged", TABLES) == []  # (and with no pool a bow is never assumed)


def test_melee_damage_never_has_the_shield_setup_and_a_setup_still_needs_its_skill_and_a_wearer():
    shield, _ = invented_pool()
    for trio in TRIOS:
        if "melee" in offered(trio):
            assert "1h-shield" not in weapons.setups_for(trio, "melee", TABLES, items=[shield]), trio
    # no shield in the pool (or one that nobody of the trio can wear): no shield setup in any build, and the casting builds keep the stick
    wearer = make_item("it-other-shield", {"SECONDARY"}, classes=("CLR",), shield=True)
    for items in ([], [wearer]):
        assert weapons.setups_for(("WAR", "SHM", "ENC"), "tank", TABLES, items=items) == ["2h", "dw"]
        assert weapons.setups_for(("WAR", "SHM", "ENC"), "shield", TABLES, items=items) == ["stick"]
        assert weapons.setups_for(("DRU", "WIZ", "ENC"), "castertank", TABLES, items=items) == ["stick"]
    # a trio with no two-hander skill has no 2h, with no dual wield skill no dw (a Monk trio of spell classes has no weapon skill but its own: the stick is what is left)
    skills = {(code, skill, 50): 100 for code, skill in (("CLR", "1H Blunt"),)}
    bare = SimpleNamespace(skillcap=skills, rules=RULES)
    assert weapons.setups_for(("CLR", "DRU", "SHM"), "tank", bare, items=[shield]) == ["1h-shield"]
    assert weapons.setups_for(("CLR", "DRU", "SHM"), "melee", bare, items=[shield]) == ["stick"]


def test_every_offered_build_has_a_setup_with_a_pool_and_with_none():
    shield, bow = invented_pool()
    for trio in TRIOS:
        with_bow = weapons.bow_available(trio, [shield, bow], tables=TABLES, level=50)
        for build in roles.roles_for(trio, bow=with_bow):
            assert weapons.setups_for(trio, build, TABLES, items=[shield, bow]), (trio, build, "a pool with a shield and a bow")
        for build in roles.roles_for(trio, bow=False):  # (the Archer aside: it has no setup with no pool, by design, as today)
            assert weapons.setups_for(trio, build, TABLES), (trio, build, "no pool")
            assert weapons.setups_for(trio, build, TABLES, items=[]), (trio, build, "an empty pool")


def test_every_offered_build_has_a_setup_with_the_wiki_pool_of_the_real_catalog_for_all_560_trios():
    """The pool is the wiki level of the shipped catalog (the strict and the wiki items, no deity-locked one), read by the project's own loader and selection: the shields and the bows it
    holds decide the shield and bow setups, for each trio, as a release makes them."""
    from types import SimpleNamespace

    from trioforge.precompute import grid

    path = grid.find_catalog()
    if path is None:
        pytest.skip("derived/catalog.json is not built")
    items = load_strict(path)["items"]
    rules = TABLES.rules
    offered_to = Counter()
    for trio in itertools.combinations(CLASS_CODES, 3):
        selection = grid.select_items(items, trio)
        pool = grid.setup_pool(SimpleNamespace(items=selection.items, levels=selection.levels), rules, "wiki")  # (what a run reads to decide the setups of the level)
        with_bow = weapons.bow_available(trio, pool, tables=TABLES, level=50)
        builds = roles.roles_for(trio, bow=with_bow)
        assert 1 <= len(builds) <= 4, (trio, builds)
        for build in builds:
            assert weapons.setups_for(trio, build, TABLES, level=50, items=pool), (trio, build)
            offered_to[build] += 1
        if "RNG" in trio:
            assert ("ranged" in builds) == with_bow, trio  # (the Archer is offered where the pool has a bow a class of the trio can shoot)
    assert set(offered_to) == set(BUILDS)  # (every build is offered to some trio of the real catalog)
    assert offered_to["tank"] == 274 and offered_to["shield"] == 210 and offered_to["melee"] == 525 and offered_to["castertank"] == 161 and offered_to["caster"] == 224  # (as for no pool)


# ---- the opening build ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trio", "expected"),
    [
        (("SHD", "WIZ", "ENC"), "shield"),
        (("WAR", "SHM", "ENC"), "tank"),  # a Warrior with a Shaman and an Enchanter: the tank-hybrid
        (("PAL", "MNK", "ENC"), "tank"),
        (("PAL", "CLR", "DRU"), "shield"),
        (("SHD", "NEC", "SHM"), "shield"),
        (("WAR", "CLR", "WIZ"), "shield"),  # a Warrior with a Wizard and another spell class
        (("WAR", "WIZ", "ENC"), "shield"),
        (("WAR", "CLR", "DRU"), "tank"),  # a Warrior without a Wizard
        (("WAR", "CLR", "MNK"), "tank"),
        (("WAR", "WIZ", "ROG"), "tank"),  # a Wizard, but one spell class only
        (("RNG", "SHM", "CLR"), "ranged"),
        (("RNG", "MNK", "ROG"), "ranged"),  # a Ranger with no tank class
        (("WAR", "RNG", "ROG"), "tank"),  # a Ranger with a tank class: the tank leads
        (("DRU", "WIZ", "ENC"), "caster"),  # a pet class is present
        (("CLR", "DRU", "SHM"), "castertank"),  # no pet class
        (("WIZ", "CLR", "DRU"), "castertank"),
        (("MNK", "SHM", "ENC"), "melee"),  # a Monk is the front of its trio
        (("MNK", "ROG", "BER"), "melee"),
        (("BRD", "ROG", "BST"), "melee"),
        (("WIZ", "ROG", "BRD"), "melee"),  # at most one spell class
        (("WIZ", "MAG", "ENC"), "caster"),
    ],
)
def test_the_opening_build_of_the_examples(trio, expected):
    assert roles.opening_role(trio) == expected


def test_the_opening_build_of_every_trio_is_one_it_is_offered_and_the_function_never_raises():
    counts, no_bow = Counter(), Counter()
    for trio in TRIOS:
        build = roles.opening_role(trio)  # (it raises for a trio that no rule matches)
        assert build in roles.roles_for(trio, bow=None), (trio, build)
        counts[build] += 1
        without = roles.opening_role(trio, roles.roles_for(trio, bow=False))  # (no bow in the pool: the Archer rule is skipped)
        assert without in roles.roles_for(trio, bow=False) and without != "ranged", (trio, without)
        no_bow[without] += 1
        if build != "ranged":
            assert without == build  # (only the Archer rule depends on the pool)
        members = set(trio)
        # the rules of the work order, one by one, written again
        if "RNG" in members and not members & TK:
            assert build == "ranged"
        elif members & TK:
            spell_knight = len(members & SPELL) >= 2 and (members & {"SHD", "PAL"} or {"WAR", "WIZ"} <= members)
            assert build == ("shield" if spell_knight else "tank")
        elif "MNK" in members or len(members & SPELL) <= 1:
            assert build == "melee"
        else:
            assert build == ("caster" if members & PETC else "castertank")
    assert dict(counts) == OPENING_COUNTS
    assert dict(no_bow) == OPENING_COUNTS_NO_BOW


def test_the_opening_build_function_refuses_what_it_cannot_answer():
    with pytest.raises(ValueError, match="trio"):
        roles.opening_role(("WAR", "WAR", "CLR"))
    with pytest.raises(ValueError, match="not offered"):
        roles.opening_role(("SHD", "WIZ", "ENC"), ["tank", "melee"])  # the rule says Shield caster, which is not in the list


# ---- the default race -----------------------------------------------------------------------------------------------------


def test_the_default_race_is_the_best_that_can_be_created_and_the_close_races_are_listed():
    from trioforge.precompute import shards

    order = ["HUM", "BAR", "ERU", "ELF", "HIE"]
    values = {"HUM": 100.0, "BAR": 99.0, "ERU": 98.99, "ELF": 99.5, "HIE": 120.0}  # HIE is best, but cannot be created
    legal = ("HUM", "BAR", "ERU", "ELF")
    choice = shards.default_race(values, legal, order, 1)
    assert choice["race"] == "HUM" and choice["runner_up"] == "ELF" and choice["margin"] == pytest.approx(0.5)
    assert choice["close"] == ["HUM", "ELF", "BAR"]  # within one percent of the best, in descending value, the default first; exactly 99 is in, 98.99 is out, HIE is not named
    # the best that stands alone is not close to anything; a tie goes to the display order; the band is the rule's, in exact arithmetic on the decimals
    assert shards.default_race({"HUM": 100.0, "BAR": 98.0}, ("HUM", "BAR"), order, 1)["close"] == []
    assert shards.default_race({"HUM": 100.0, "BAR": 100.0, "ERU": 100.0}, ("HUM", "BAR", "ERU"), order, 1)["close"] == ["HUM", "BAR", "ERU"]
    assert shards.default_race({"HUM": 100.0, "BAR": 98.0}, ("HUM", "BAR"), order, 2)["close"] == ["HUM", "BAR"]
    assert shards.default_race({"HUM": 0.0, "BAR": 0.0}, ("HUM", "BAR"), order, 1)["close"] == []  # (a share of nothing has no meaning)
    assert shards.default_race({"HUM": 7.0}, ("HUM",), order, 1) == {"race": "HUM", "runner_up": None, "margin": None, "close": []}
    assert shards.default_race({"HIE": 7.0}, ("HUM",), order, 1) is None
    assert RULES.get("defaults.race_close_pct") == 1 and RULES.seal("defaults.race_close_pct") == "model"


# ---- the templates and the weapon factor -----------------------------------------------------------------------------------


STARTING_VALUES = {
    "tank": {"HP": 1, "AC": 12, "MANA": 0.15, "ATK": 2.67, "DEX": 0.1, "HASTE": 1.5, "END": 0.5, "SV": 0.4, "CHA": 0.05},
    "shield": {"HP": 1, "AC": 12, "MANA": 0.3, "ATK": 0.3, "DEX": 0.05, "HASTE": 0, "END": 0.25, "SV": 1.5, "CHA": 0.05},
    "melee": {"HP": 1.3, "AC": 1.5, "MANA": 0.15, "ATK": 4.0, "DEX": 0.8, "HASTE": 3, "END": 0.3, "SV": 0.2, "CHA": 0.05},
    "castertank": {"HP": 1, "AC": 9, "MANA": 1, "ATK": 0.1, "DEX": 0.05, "HASTE": 0, "END": 0.3, "SV": 0.8, "CHA": 0.05},
    "caster": {"HP": 1, "AC": 1.2, "MANA": 4.0, "ATK": 0.3, "DEX": 0.1, "HASTE": 0, "END": 0.05, "SV": 0.8, "CHA": 0.05},
}


def test_the_templates_are_the_starting_values_of_the_work_order_and_a_judgment():
    assert RULES.get("roles.templates") == STARTING_VALUES
    assert RULES.get("roles.ranged_template") == {"DEX": 2, "AC": 0.5}  # (as it was: the Archer is the new Melee template with these factors)
    assert RULES.get("weapons.damage_weight") == 450
    for rule_id in ("roles.templates", "roles.weapon_factor", "weapons.damage_weight", "haste.assume_spell", "defaults.race_close_pct"):
        rule = next(rule for rule in RAW["rules"] if rule["id"] == rule_id)
        assert rule["seal"] == "model" and rule["source"] == [{"kind": "public-text", "ref": "TrioForge judgment"}], rule_id
        assert "judgment" in rule["notes"].lower(), rule_id  # in plain words: it is a judgment, not a measurement
        assert "private" not in rule["notes"].lower() and "player" not in rule["notes"].lower() and "forum" not in rule["notes"].lower(), rule_id
    assert "roles.balanced" not in {rule["id"] for rule in RAW["rules"]}


def test_the_weapon_damage_weight_of_each_build_is_one_mechanism_a_factor_on_the_rule_times_the_attack_weight():
    assert RULES.get("roles.weapon_factor") == {"tank": 0.5, "shield": 0, "melee": 1, "ranged": 1, "castertank": 0, "caster": 0}
    assert RULES.get("weapons.damage_weight") * RULES.get("roles.templates")["melee"]["ATK"] == 1800  # (the product for melee stays 1800)
    expected = {"tank": 450 * 2.67 * 0.5, "shield": 0, "melee": 1800, "ranged": 1800, "castertank": 0, "caster": 0}
    trios = {"tank": ("WAR", "CLR", "DRU"), "shield": ("WAR", "CLR", "DRU"), "melee": ("WAR", "CLR", "DRU"), "ranged": ("RNG", "SHM", "CLR"),
             "castertank": ("DRU", "WIZ", "ENC"), "caster": ("DRU", "WIZ", "ENC")}
    for build, trio in trios.items():
        assert roles.weights_for(trio, build, RULES)["DMG"] == pytest.approx(expected[build]), build
    # a weight of the Caster build with the factor raised is the rule times its own attack weight (the factor is the only thing that says "no damage")
    raised = rules_with(**{"roles.weapon_factor": {**RULES.get("roles.weapon_factor"), "caster": 2}})
    assert roles.weights_for(("DRU", "WIZ", "ENC"), "caster", raised)["DMG"] == pytest.approx(450 * 0.3 * 2)
    # a table that does not name every build is refused
    with pytest.raises(ValueError, match="roles.weapon_factor"):
        roles.weights_for(("DRU", "WIZ", "ENC"), "caster", rules_with(**{"roles.weapon_factor": {"tank": 1}}))


def test_a_build_the_trio_is_not_offered_has_no_weights():
    for trio, build in ((("WAR", "PAL", "SHD"), "shield"), (("DRU", "WIZ", "ENC"), "tank"), (("MNK", "ROG", "BER"), "caster"), (("WAR", "CLR", "MNK"), "caster")):
        with pytest.raises(ValueError, match="not offered"):
            roles.weights_for(trio, build, RULES)
    with pytest.raises(ValueError, match="not offered"):
        roles.weights_for(("WAR", "CLR", "DRU"), "balanced", RULES)


def weapon_pool():
    """Two one-handed weapons for the two hands: a blade with a lot of damage and no stats, and a plain one with armour class and hit points."""
    blade = make_item("it-blade", {"PRIMARY", "SECONDARY"}, weapon=WeaponVec("1H Slashing", 120, 20, None, False))
    plain = make_item("it-plain", {"PRIMARY", "SECONDARY"}, stats={"AC": 6, "HP": 60}, weapon=WeaponVec("1H Slashing", 1, 90, None, False))
    return [blade, plain]


def hands(rules):
    """The kit of a Tank at dual wield from ``weapon_pool`` under ``rules``: the keys in the main hand and the off hand."""
    pool = weapon_pool()
    profile = make_profile("HUM", ("WAR", "CLR", "DRU"), 50, "tank", None, None, TABLES, rules, items=pool)
    solved = solve_scenario(profile, pool, "dw", None, BuildOptions(any_rule="explicit"))
    kit = {name: item.key for name, item in zip(("PRIMARY", "SECONDARY"), solved.solution.kit[-2:]) if item is not None}
    return profile, kit


def test_a_tank_with_a_weapon_factor_of_zero_picks_the_hands_on_stats_and_armour_class_alone():
    zero = {**RULES.get("roles.weapon_factor"), "tank": 0}
    profile, kit = hands(rules_with(**{"roles.weapon_factor": zero}))
    assert profile.weights["DMG"] == 0 and profile.eval_profile.weights["DMG"] == 0
    assert kit == {"PRIMARY": "it-plain", "SECONDARY": "it-plain"}  # the plain weapon carries the armour class and the hit points
    full = {**RULES.get("roles.weapon_factor"), "tank": 1}
    profile, kit = hands(rules_with(**{"roles.weapon_factor": full}))
    assert profile.weights["DMG"] == pytest.approx(450 * 2.67)
    assert kit == {"PRIMARY": "it-blade", "SECONDARY": "it-blade"}  # with the damage counted in full the blade wins both hands


# ---- haste.assume_spell ----------------------------------------------------------------------------------------------------


def test_the_haste_rule_is_false_and_a_model_judgment():
    assert RULES.get("haste.assume_spell") is False and RULES.seal("haste.assume_spell") == "model"
    assert buff_model.assumes_spell_haste(RULES) is False
    assert buff_model.assumes_spell_haste(rules_with(**{"haste.assume_spell": True})) is True
    with pytest.raises(ValueError, match="true or false"):
        buff_model.assumes_spell_haste(rules_with(**{"haste.assume_spell": "yes"}))


def profile_facts(trio, race, key, rules, **kwargs):
    sets = buff_model.buffsets(trio, 50, SPELLS, rules, (key,), **kwargs)
    profile = make_profile(race, trio, 50, roles.roles_for(trio, bow=None)[0], sets[key], None, TABLES, rules)
    return sets[key], profile


def test_with_the_rule_true_the_profile_is_what_the_code_before_the_builds_made():
    document = json.loads((REPO / "fixtures" / "builds" / "haste-profiles-main.json").read_text(encoding="utf-8"))
    rules = rules_with(**{"haste.assume_spell": True})
    assert len(document["cases"]) >= 40
    for case in document["cases"]:
        trio = tuple(case["trio"].upper().split("-"))
        buffset, profile = profile_facts(trio, case["race"], case["buffs"], rules)
        where = (case["trio"], case["race"], case["buffs"])
        assert profile.spell_haste == case["spell_haste"], where
        assert profile.haste_bonus == case["haste_bonus"], where
        assert profile.to_dict()["buff_totals"] == case["buff_totals"], where
        assert [buff.id for buff in buffset.always_on] == case["always_on"], where
        assert [buff.id for buff in buffset.optional] == case["optional"], where
        assert buffset.cardinality == case["cardinality"], where
        assert {str(buff.id): buff.haste for buff in buffset.optional if buff.haste} == case["optional_haste"], where


def test_with_the_rule_false_no_spell_haste_enters_the_profile_the_solver_or_the_evaluator():
    document = json.loads((REPO / "fixtures" / "builds" / "haste-profiles-main.json").read_text(encoding="utf-8"))
    some_haste = 0
    for case in document["cases"]:
        trio = tuple(case["trio"].upper().split("-"))
        buffset, profile = profile_facts(trio, case["race"], case["buffs"], RULES)  # (the rule as the file has it: false)
        where = (case["trio"], case["race"], case["buffs"])
        assert profile.spell_haste == case["haste_bonus"], where  # the weapon-skill bonus alone: the Monk's 10, else 0
        assert profile.to_dict()["buff_totals"].get("HASTE", 0) == 0, where
        assert all(buff.haste == 0 for buff in (*buffset.always_on, *buffset.optional)), where
        assert buffset.totals(())["haste"] == 0, where
        some_haste += bool(case["optional_haste"] or case["spell_haste"] - case["haste_bonus"])
    assert some_haste > 20  # (the cases do have spell haste to take out)


def test_the_haste_a_buff_set_would_give_is_still_there_to_ask_for():
    trio = ("WAR", "SHM", "ENC")
    kept, profile = profile_facts(trio, "HUM", "own", RULES, spell_haste=True)  # (what the browser's "I have a haste spell" solves with)
    assert profile.spell_haste == 60 and any(buff.haste == 60 for buff in kept.optional)
    stripped, profile = profile_facts(trio, "HUM", "own", RULES)
    assert profile.spell_haste == 0 and not any(buff.haste for buff in stripped.optional)
    assert len(stripped.optional) < len(kept.optional)  # (the haste spells themselves are inert without it, and left out)
    for key in buff_model.BUFF_SETS:
        _, with_rule_true = profile_facts(trio, "HUM", key, rules_with(**{"haste.assume_spell": True}))
        _, forced = profile_facts(trio, "HUM", key, RULES, spell_haste=True)
        assert with_rule_true == forced, key
    with pytest.raises(ValueError, match="unknown buff set"):
        buff_model.buffsets(trio, 50, SPELLS, RULES, ("nope",))


def test_a_worn_haste_item_is_worth_its_full_value_when_no_haste_spell_is_assumed():
    """A belt of 20 haste beside a spell of 60 counts for 15 of the 75 (the cap) when the spell is assumed, and for all 20 when it is not."""
    trio = ("WAR", "SHM", "ENC")
    blade = make_item("it-blade", {"PRIMARY"}, weapon=WeaponVec("2H Slashing", 60, 30, None, True))
    belt = make_item("it-belt", {"WAIST"}, haste=20)
    sash = make_item("it-sash", {"WAIST"}, haste=15)
    for assume, counted in ((True, 75), (False, 20)):
        rules = rules_with(**{"haste.assume_spell": assume})
        sets = buff_model.buffsets(trio, 50, SPELLS, rules, ("own",))
        profile = make_profile("HUM", trio, 50, "melee", sets["own"], None, TABLES, rules, items=[blade, belt, sash])
        solved = solve_scenario(profile, [blade, belt, sash], "2h", sets["own"], BuildOptions(any_rule="explicit"))
        assert solved.haste == counted, (assume, solved.haste)


# ---- results: no Balanced anywhere, and an old results folder is refused -----------------------------------------------------


SOLVED = REPO / "fixtures" / "site" / "results-solved"
HAND_WRITTEN = REPO / "fixtures" / "site" / "results"
SLUG = "pal-mnk-ber"


def texts_under(folder):
    return {path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8") for path in sorted(folder.rglob("*")) if path.is_file()}


@pytest.mark.parametrize("folder", [SOLVED, HAND_WRITTEN], ids=["solved", "hand-written"])
def test_no_results_folder_of_the_repository_holds_the_balanced_build(folder):
    for name, text in texts_under(folder).items():
        assert "balanced" not in name.lower(), name
        assert "balanced" not in text.lower(), name
    defaults = json.loads((folder / SLUG / "defaults.json").read_text(encoding="utf-8"))
    assert defaults["view"]["role"] == roles.opening_role(("PAL", "MNK", "BER")) == "tank"
    assert defaults["close_races"] == [] or defaults["close_races"][0] == defaults["race"]
    for name in ("wiki-own.json", "strict-own.json"):
        shard = json.loads((folder / SLUG / name).read_text(encoding="utf-8"))
        assert set(shard["roles"]) <= set(BUILDS) and "balanced" not in shard["setups"], name
        assert {row[1] for row in shard["scenarios"]} <= set(BUILDS), name
    bundle = json.loads((folder / SLUG / "engine-l50.json").read_text(encoding="utf-8"))
    assert list(bundle["roles"]) and set(bundle["roles"]) <= set(BUILDS)
    for path in (folder / SLUG / "runnerups").glob("*.json"):
        assert path.stem == "index" or path.stem in BUILDS, path.name


BALANCED_FORMS = ["defaults", "shard", "chunk", "chunk-runnerup", "robust", "runnerups"]  # the ways a folder shows the Balanced build
VERSION_FORMS = ["narrowed", "index-only", "engine-only", "exalt-only"]  # the ways a folder shows rules other than these, with no Balanced in it
EARLIER_RULES = "2026-10-13"
BALANCED_WORDS = r"Balanced build.*no longer exists.*new results folder"


def words_for(how):
    if how in BALANCED_FORMS:
        return BALANCED_WORDS
    return rf"other rules.*rules_version {EARLIER_RULES}.*this is rules version {load_rules().version}.*new results folder"


def rewrite_version(path, version=EARLIER_RULES):
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(r'("rules_version"\s*:\s*")[^"]*"', lambda m: m.group(1) + version + '"', text, count=1), encoding="utf-8")


def old_folder(tmp_path, how):
    """A results folder of a trio as the earlier release made it (or its rules), in one of the ways that show it."""
    folder = tmp_path / "results" / SLUG
    if how == "chunk":
        (folder / "chunks").mkdir(parents=True)
        (folder / "chunks" / "s-wiki-own-balanced-dw-t04.json").write_text("{}", encoding="utf-8")
    elif how == "chunk-runnerup":
        (folder / "chunks").mkdir(parents=True)
        (folder / "chunks" / "r-balanced-t04.json").write_text("{}", encoding="utf-8")
    elif how == "runnerups":
        (folder / "runnerups").mkdir(parents=True)
        (folder / "runnerups" / "balanced.json").write_text("{}", encoding="utf-8")
    elif how == "index-only":  # the index of the runner-up files of the earlier code, and nothing else
        (folder / "runnerups").mkdir(parents=True)
        shutil.copy(HAND_WRITTEN / SLUG / "runnerups" / "index.json", folder / "runnerups" / "index.json")
        rewrite_version(folder / "runnerups" / "index.json")
    elif how == "engine-only":  # the bundle of the earlier code, and nothing else
        folder.mkdir(parents=True)
        shutil.copy(HAND_WRITTEN / SLUG / "engine-l50.json", folder / "engine-l50.json")
        rewrite_version(folder / "engine-l50.json")
    elif how == "exalt-only":  # the exaltation file of the earlier code (invented: only the header)
        folder.mkdir(parents=True)
        (folder / "exalt.json").write_text(json.dumps({"version": 1, "trio": SLUG, "rules_version": EARLIER_RULES}), encoding="utf-8")
    else:
        shutil.copytree(HAND_WRITTEN / SLUG, folder)
        if how == "defaults":
            path = folder / "defaults.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["view"]["role"] = "balanced"
            path.write_text(json.dumps(document), encoding="utf-8")
        elif how == "shard":  # a shard that lists the build
            path = folder / "wiki-own.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["roles"] = ["balanced", *document["roles"]]
            path.write_text(json.dumps(document), encoding="utf-8")
        elif how == "robust":  # the seals of a build that no longer exists
            path = folder / "robust.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["roles"]["balanced"] = document["roles"]["tank"]
            path.write_text(json.dumps(document), encoding="utf-8")
        else:  # "narrowed": an old run of the Tank alone: its four shards, with the rules of the earlier release, and no other file
            for path in folder.rglob("*"):
                if path.is_file() and path.name not in ("strict-own.json", "strict-group.json", "wiki-own.json", "wiki-group.json"):
                    path.unlink()
            for name in ("strict-own.json", "strict-group.json", "wiki-own.json", "wiki-group.json"):
                path = folder / name
                document = json.loads(path.read_text(encoding="utf-8"))
                document.update(roles=["tank"], setups={"tank": document["setups"]["tank"]}, scenarios=[row for row in document["scenarios"] if row[1] == "tank"], rules_version=EARLIER_RULES)
                path.write_text(json.dumps(document), encoding="utf-8")
    return folder


@pytest.mark.parametrize("how", [*BALANCED_FORMS, *VERSION_FORMS])
def test_the_precompute_refuses_to_resume_into_the_results_of_the_earlier_builds_or_rules(tmp_path, how):
    from trioforge import precompute

    folder = old_folder(tmp_path, how)
    before = texts_under(folder)
    with pytest.raises(precompute.PrecomputeError, match=words_for(how)):
        precompute.run(SLUG, tmp_path / "results", catalog=tmp_path / "no-catalog.json", processes=1, tiers=[0, 4], robustness=False)
    assert texts_under(folder) == before  # nothing was read half-way or written over


@pytest.mark.parametrize("how", [*BALANCED_FORMS, *VERSION_FORMS])
def test_a_release_run_of_a_trio_reports_the_old_folder_as_a_failure_with_the_same_words(tmp_path, how):
    from engine_fixture import catalog

    from trioforge.precompute import release

    path = tmp_path / "catalog.json"
    path.write_bytes(json.dumps(catalog(), sort_keys=True, separators=(",", ":")).encode("utf-8"))  # (the invented catalog of the site fixture)
    folder = old_folder(tmp_path, how)
    before = texts_under(folder)
    spec = release.TrioSpec(slug=SLUG, results=str(tmp_path / "results"), catalog=str(path))
    outcome = release.run_trio(spec)
    assert outcome.status == "failed" and re.search(words_for(how), outcome.error), outcome.error
    assert texts_under(folder) == before


@pytest.mark.parametrize("how", [*BALANCED_FORMS, *VERSION_FORMS])
def test_the_sites_reader_refuses_an_old_folder_with_a_clear_message_and_reads_none_of_it(tmp_path, how):
    from trioforge.site import data

    folder = old_folder(tmp_path, how)
    with pytest.raises(data.ResultsError, match=words_for(how)):
        data.load_trio(folder)
    assert data.load_trio(HAND_WRITTEN / SLUG).defaults.role == "tank"  # (the folder of this release is read)


def test_a_folder_of_the_current_rules_is_refused_by_none_of_the_three_and_a_reader_given_the_earlier_version_refuses_it(tmp_path):
    from trioforge.oldresults import stale
    from trioforge.site import data

    assert load_rules().version != EARLIER_RULES
    assert data.load_trio(HAND_WRITTEN / SLUG).meta.slug == SLUG  # (a folder of the rules file's version is read)
    assert stale(SLUG, HAND_WRITTEN / SLUG) is None and stale(SLUG, SOLVED / SLUG) is None  # (the solved fixture holds no runner-ups, so only the test of the rules is made on it)
    with pytest.raises(data.ResultsError, match=rf"other rules.*rules_version {load_rules().version}.*this is rules version {EARLIER_RULES}"):
        data.load_trio(HAND_WRITTEN / SLUG, rules_version=EARLIER_RULES)


# ---- the order of a build's setups decides a tie ------------------------------------------------------------------------------------------


def test_the_first_setup_of_a_build_wins_a_tie_and_for_the_caster_that_is_the_stick():
    from trioforge.site import data as site_data

    assert weapons.setup_order("caster")[:2] == ("stick", "1h-shield")
    for role in ("tank", "shield", "melee", "ranged", "castertank"):
        assert weapons.setup_order(role) == weapons.SETUPS, role  # (the others keep the order of SETUPS: the shield before the stick)
    assert site_data.setup_order("caster") == weapons.setup_order("caster") and site_data.SETUPS == weapons.SETUPS  # (the reader's copy of the vocabulary)
    for role in roles.ROLES:
        assert site_data.setup_order(role) == weapons.setup_order(role), role


def test_the_reader_gives_a_tie_between_the_stick_and_the_shield_to_the_stick_for_the_caster_and_to_the_shield_for_the_shield_caster():
    from trioforge.site import data as site_data

    def scenario(role, setup):
        totals = site_data.Totals(0, 0, 0, 0, 0, 0, (0, 0, 0, 0, 0), (0, 0, 0))
        return site_data.Scenario("OGR", role, 4, setup, (None,) * 22, 100.0, 0.0, totals, (), 0)

    shard = site_data.Shard("wiki", "own", (), tuple(scenario(role, setup) for role in ("caster", "shield") for setup in ("1h-shield", "stick")))
    assert shard.setups_for("caster") == ("stick", "1h-shield") and shard.setups_for("shield") == ("1h-shield", "stick")
    assert shard.best_setup("OGR", "caster", 4) == "stick" and shard.best_setup("OGR", "shield", 4) == "1h-shield"


def test_the_setups_a_plan_lists_for_each_build_are_in_the_order_of_the_build_so_that_the_first_wins_a_tie():
    from trioforge.precompute import engine, grid

    plan = [grid.Scenario("OGR", role, 4, "wiki", "own", setup) for role in ("caster", "shield") for setup in ("1h-shield", "stick")]
    assert engine.level_setups(plan) == {"wiki": {"caster": ["stick", "1h-shield"], "shield": ["1h-shield", "stick"]}}


# ---- the notes of the rules of the builds say what the rules are --------------------------------------------------------------------------


def raw_rules():
    return json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"]


def note_of(rule_id):
    (rule,) = [rule for rule in raw_rules() if rule["id"] == rule_id]
    return rule["notes"]


def test_a_note_that_cites_a_rule_by_its_title_cites_a_title_the_rules_file_has():
    rules = raw_rules()
    titles = [rule["title"] for rule in rules]
    for rule in rules:
        for found in re.finditer(r"the rule (?=[A-Z])", rule.get("notes", "")):
            rest = rule["notes"][found.end() :]
            assert any(rest.startswith(title) for title in titles), (rule["id"], rest[:60])


def test_the_tank_note_gives_the_factor_and_the_real_product_and_not_half_the_melee_weight():
    for rule_id in ("roles.templates", "roles.weapon_factor"):
        note = note_of(rule_id)
        assert "half the Melee weight" not in note and "600.75" in note and "0.5" in note, rule_id
    assert 450 * 2.67 * 0.5 == pytest.approx(600.75) and 450 * 4 * 1 == 1800  # (the product the notes give, and the Melee weight it is a third of)


def test_the_haste_rule_note_describes_the_rule_and_the_readers_box_that_stage_two_built():
    note = note_of("haste.assume_spell")
    assert "judgment" in note and "I have a haste spell" in note and "browser" in note.lower()  # (stage 1 promised no switch: the box is built now, and the note says what it is)


def test_the_ranged_note_names_the_templates_rule_by_its_present_title():
    note = note_of("roles.ranged_template")
    assert "Role weight templates" not in note and "the rule Build weight templates" in note


# ---- fix round 2: a trio file that records no rules version is old, and the reader's list of builds that play no bow is the weapon module's -------------------------


NO_VERSION_FORMS = ["missing", "null", "past-the-header"]  # the ways a file of a trio records no rules version


def without_version(folder, how, name="wiki-own.json"):
    path = folder / name
    document = json.loads(path.read_text(encoding="utf-8"))
    if how == "null":
        document["rules_version"] = None
    else:
        del document["rules_version"]
    if how == "past-the-header":  # the version is there, but after the bytes that are read for it: a file that no writer makes
        document = {"padding": "x" * 20000, **document, "rules_version": load_rules().version}
    path.write_text(json.dumps(document), encoding="utf-8")


@pytest.mark.parametrize("how", NO_VERSION_FORMS)
@pytest.mark.parametrize("name", ["wiki-own.json", "defaults.json", "runnerups/tank.json", "runnerups/index.json", "robust.json", "engine-l50.json"])
def test_a_trio_file_with_no_rules_version_is_old_as_the_sites_reader_and_the_checker_treat_it(tmp_path, how, name):
    from trioforge.oldresults import other_rules_files, stale
    from trioforge.site import data

    folder = tmp_path / "results" / SLUG
    shutil.copytree(HAND_WRITTEN / SLUG, folder)
    assert stale(SLUG, folder) is None
    without_version(folder, how, name)
    assert other_rules_files(folder, load_rules().version) == [(name, None)]
    assert re.search(rf"other rules.*{re.escape(name)} records no rules_version.*this is rules version {load_rules().version}.*new results folder", stale(SLUG, folder))
    with pytest.raises(data.ResultsError, match=rf"other rules.*{re.escape(name)} records no rules_version"):
        data.load_trio(folder)


def test_a_file_of_no_name_a_writer_gives_a_trio_folder_is_not_asked_for_a_rules_version(tmp_path):
    from trioforge.oldresults import stale

    folder = tmp_path / "results" / SLUG
    shutil.copytree(HAND_WRITTEN / SLUG, folder)
    (folder / "notes.json").write_text("{}", encoding="utf-8")  # (a scratch file of the person who runs the build)
    assert stale(SLUG, folder) is None
    (folder / "notes.json").write_text(json.dumps({"rules_version": EARLIER_RULES}), encoding="utf-8")  # (but one that does say other rules says it)
    assert stale(SLUG, folder) is not None


def test_the_builds_that_the_reader_says_never_play_the_bow_are_those_the_weapon_module_gives_no_bow_setup():
    from trioforge.site import data as site_data

    bow = make_item("bow", {"RANGE"}, weapon=WeaponVec("Archery", 10, 30, None, False), classes=("RNG", "WAR", "CLR"))
    with_a_bow = {role for role in BUILDS if "ranged" in weapons.setups_for(("RNG", "WAR", "CLR"), role, TABLES, level=50, items=[bow])}
    assert with_a_bow == set(BUILDS) - set(site_data.NO_BOW_ROLES)  # (the Archer plays the bow, the Tank and Melee damage may; the casting builds never do)
    assert set(site_data.NO_BOW_ROLES) == set(BUILDS) - weapons._BOW_ROLES - {"ranged"}
    assert list(site_data.NO_BOW_ROLES) == [role for role in BUILDS if role in site_data.NO_BOW_ROLES]  # (in the order of the builds)


def test_the_shield_casters_mana_weight_is_a_small_one_and_its_note_says_why():
    # a knight with two casters beside it has mana to spare, and gears for armour and resists: 0.3 a point, a fifth of what it was (1.5)
    assert RULES.get("roles.templates")["shield"]["MANA"] == 0.3
    (rule,) = [rule for rule in raw_rules() if rule["id"] == "roles.templates"]
    shield = rule["notes"].split("Shield caster:")[1].split("Melee damage:")[0]
    assert "mana to spare" in shield and "armour" in shield and "resists" in shield and "0.3" in shield
    assert rule["seal"] == "model" and rule["source"] == [{"kind": "public-text", "ref": "TrioForge judgment"}] and rule["date"] == "2026-11-19"
    assert RULES.version == "2026-11-19"  # (nothing was released under this version: it stays)



STATIC = Path(__file__).resolve().parents[1] / "trioforge" / "site" / "static"


def test_the_browsers_order_of_the_setups_is_the_pipelines():
    """``shard.js`` orders the setups of a build as :func:`weapons.setup_order` does: the order of the setups of the page, with the one a build lists first (the Caster's stick, which wins a tie) in front."""
    text = (STATIC / "shard.js").read_text(encoding="utf-8")
    order = re.search(r"export const SETUP_ORDER = \[(.*?)\];", text).group(1)
    assert [name.strip().strip('"') for name in order.split(",")] == list(weapons.SETUPS)
    listed = re.search(r"export const LISTED_FIRST = \{(.*?)\};", text).group(1)
    pairs = dict(re.findall(r"(\w+):\s*\"([\w-]+)\"", listed))
    assert pairs == weapons._LISTED_FIRST
    for role in BUILDS:
        first = pairs.get(role)
        js = list(weapons.SETUPS) if first is None else [first, *(name for name in weapons.SETUPS if name != first)]
        assert js == list(weapons.setup_order(role)), role


def test_the_bundle_has_the_haste_twins_that_the_page_and_the_engine_name():
    """The suffix of the page (``HASTE`` of ``trio.js``) and of the engine (``HASTE_SUFFIX`` of ``engine/profile.js``) are the exporter's."""
    for name in ("trio.js", "engine/profile.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert re.search(r'(?:const HASTE|export const HASTE_SUFFIX) = "([^"]+)"', text).group(1) == browser.HASTE_SUFFIX, name
