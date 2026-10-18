"""Tests for the browser exports: ``trioforge.export.browser`` (``bundle``, ``items``, ``assemble`` and the command).

A **bundle** is everything the browser engine needs about one trio at one level, in one JSON object: the profile
parts (those every scenario shares, and those that depend on the race, the role or the buff set), the four resolved buff
sets, the constants of the formulas, the Monk bonus per whole stone, the tier and weapon rules, the weight groups and
the regen ratios. ``assemble(bundle, race, role, buffs)`` is the Python reference for putting the parts back together,
and it must give exactly ``make_profile(...).to_dict()``; the tests check that for every race, role and buff key of five
trio types. The **item table** holds every wearable of the catalog (the ones the model never recommends too, flagged
``owned_only``), sorted by wiki page id, with what ``at_tier`` reads and what the Upgrade tab needs to match a dump.

Every exact number outside the profile parts is a ``"p/q"`` string (reduced), so that no reader meets a float.
"""

import ast
import copy
import dataclasses
import gzip
import hashlib
import inspect
import itertools
import json
import math
import random
import re
import sys
from fractions import Fraction
from pathlib import Path

import pytest
from after_an_add import AfterAnAdd, strict_without_a_report

from trioforge.classes import CLASS_CODES
from trioforge.data.jsonio import loads_strict
from trioforge.export import browser
from trioforge.export.browser import BUFF_SETS, assemble, bundle, items, match_name
from trioforge.model import formulas as fm
from trioforge.model import items as items_module
from trioforge.model import roles, weapons
from trioforge.model.buffs import (
    COMPONENTS,
    enchanter_preset,
    group_preset,
    own_buffs,
    raid_preset,
    resolve,
)
from trioforge.model.items import SLOT_GROUPS, at_tier
from trioforge.model.profile import Profile, eval_buffs, make_profile
from trioforge.model.tables import load as load_tables
from trioforge.precompute import grid
from trioforge.rules import Rules

REPO = Path(__file__).resolve().parents[2]
TABLES = load_tables()
RULES = TABLES.rules
RAW_RULES = json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))
RATIONAL = re.compile(r"-?[0-9]+/[1-9][0-9]*")
# a Monk trio, a mixed WIS/INT mana trio, an all-caster trio, a trio with no mana class, a melee/caster mix
FIVE_TRIOS = [
    grid.parse_trio(trio)  # the page order of a trio: the class numbers rise
    for trio in ("PAL-MNK-BER", "SHD-CLR-SHM", "WIZ-MAG-ENC", "WAR-ROG-BER", "BRD-RNG-BST")
]
RATIONAL_BLOCKS = ("constants", "monk_bins", "tier_rules", "weapon_rules", "weight_groups", "regen_ratios")


# ---- helpers ---------------------------------------------------------------------------------------------------------


def spells_file(level):
    return json.loads((REPO / "derived" / "client" / f"spells-l{level}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def l50():
    return spells_file(50)


@pytest.fixture(scope="module")
def l55():
    return spells_file(55)


@pytest.fixture(scope="module")
def pmb(l50):
    return bundle(("PAL", "MNK", "BER"), 50, TABLES, RULES, l50, data_release="data-2030-01-02")


def decode(value):
    """A value of a rational block with every ``"p/q"`` string read as a Fraction."""
    if isinstance(value, str) and RATIONAL.fullmatch(value):
        numerator, denominator = value.split("/")
        return Fraction(int(numerator), int(denominator))
    if isinstance(value, list):
        return [decode(item) for item in value]
    if isinstance(value, dict):
        return {key: decode(item) for key, item in value.items()}
    return value


def exact(value):
    """A value of a module (numbers, tuples, mappings) as Fractions and lists, to compare with :func:`decode`."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float, Fraction)):
        return fm.fr(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [exact(item) for item in value]
    if isinstance(value, dict):
        return {key: exact(item) for key, item in value.items()}
    raise TypeError(value)


def walk(value, path=""):
    """Every (path, leaf) of a JSON value."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}[{index}]")
    else:
        yield path, value


def buffsets_for(codes, level, spells, rules=RULES):
    """The four resolved buff sets of a trio, written again from the public buff functions."""
    own = own_buffs(codes, level, spells, rules)
    group = group_preset(spells, level=level)
    return {
        "own": resolve(own, rules),
        "group": resolve([*own, *group], rules),
        "group+enchanter": resolve([*own, *group, *enchanter_preset(spells, level, rules=rules)], rules),
        "raid": resolve([*own, *raid_preset(spells, level, rules=rules)], rules),
    }


def reference_dict(codes, level, race, role, buffset, tables=TABLES, **options):
    return make_profile(race, codes, level, role, buffset, None, tables, **options).to_dict()


def path_get(root, dotted):
    node = root
    for part in dotted.split("."):
        node = node[part]
    return node


# ---- the bundle: its fields ------------------------------------------------------------------------------------------

REQUIRED = (
    "version", "data_release", "rules_version", "trio", "level", "profile_common", "evidence_levels", "races", "roles",
    "buffs", "buff_table", "constants", "monk_bins", "tier_rules", "weapon_rules", "weight_groups", "regen_ratios",
)  # fmt: skip


def test_the_bundle_has_every_top_level_field_and_none_is_empty(pmb):
    assert list(pmb) == list(REQUIRED)
    for name in REQUIRED:
        assert pmb[name] not in (None, "", [], {}), name  # a Monk trio has monk_bins too
    assert pmb["version"] == browser.FORMAT == 1
    assert pmb["rules_version"] == RULES.version
    assert pmb["data_release"] == "data-2030-01-02"
    assert pmb["trio"] == ["PAL", "MNK", "BER"] and pmb["level"] == 50
    assert list(pmb["buffs"]) == list(BUFF_SETS) == ["own", "group", "group+enchanter", "raid"]


def test_the_data_release_defaults_to_the_date_of_the_client_data(l50):
    plain = bundle(("PAL", "MNK", "BER"), 50, TABLES, RULES, l50)
    assert plain["data_release"] == f"data-{l50['provenance']['generated']}"


def test_a_trio_may_be_given_in_any_order_and_the_bundle_keeps_the_order_of_the_pages(l50):
    shuffled = bundle(("BER", "PAL", "MNK"), 50, TABLES, RULES, l50)
    assert shuffled["trio"] == ["PAL", "MNK", "BER"]
    assert shuffled == bundle(("PAL", "MNK", "BER"), 50, TABLES, RULES, l50)


def test_the_bundle_is_plain_json_and_the_same_every_time(pmb, l50):
    text = json.dumps(pmb, allow_nan=False, sort_keys=True)
    assert json.loads(text) == pmb
    again = bundle(("PAL", "MNK", "BER"), 50, TABLES, RULES, l50, data_release="data-2030-01-02")
    assert json.dumps(again, sort_keys=True) == text and json.dumps(again) == json.dumps(pmb)


def test_the_rules_default_to_the_tables_rules(l50):
    assert bundle(("PAL", "MNK", "BER"), 50, TABLES, None, l50) == bundle(("PAL", "MNK", "BER"), 50, TABLES, RULES, l50)


def test_a_bundle_for_bad_inputs_is_refused(l50, l55):
    with pytest.raises(ValueError, match="trio"):
        bundle(("PAL", "MNK"), 50, TABLES, RULES, l50)
    with pytest.raises(ValueError, match="level"):
        bundle(("PAL", "MNK", "BER"), 50, TABLES, RULES, l55)  # the spell file is for another level
    with pytest.raises(ValueError, match="level"):
        bundle(("PAL", "MNK", "BER"), 99, TABLES, RULES, l50)


# ---- the bundle puts a profile back together exactly -----------------------------------------------------------------


@pytest.mark.parametrize("trio", FIVE_TRIOS)
def test_assemble_gives_the_profile_dict_for_every_race_role_and_buff_key(trio, l50):
    made = bundle(trio, 50, TABLES, RULES, l50)
    buffsets = buffsets_for(trio, 50, l50)
    races = [entry["code"] for entry in made["races"]]
    assert sorted(races) == sorted(entry["code"] for entry in TABLES.races["races"] if entry["active"])
    checked = 0
    for race in races:
        for role in roles.roles_for(trio):
            for key in BUFF_SETS:
                expected = reference_dict(trio, 50, race, role, buffsets[key])
                got = assemble(made, race, role, key)
                assert got == expected, (trio, race, role, key)
                checked += 1
    assert checked == 15 * len(roles.roles_for(trio)) * 4


@pytest.mark.parametrize("trio", FIVE_TRIOS[:2])
def test_the_assembled_profile_has_the_same_json_text_and_loads_as_the_same_profile(trio, l50):
    made = bundle(trio, 50, TABLES, RULES, l50)
    buffsets = buffsets_for(trio, 50, l50)
    last = roles.roles_for(trio)[-1]
    for race, role, key in [("HUM", "balanced", "own"), ("IKS", "balanced", "raid"), ("OGR", last, "group")]:
        profile = make_profile(race, trio, 50, role, buffsets[key], None, TABLES)
        got = assemble(made, race, role, key)
        assert json.dumps(got, separators=(",", ":")) == profile.to_json()
        assert Profile.from_dict(got) == profile


def test_assemble_reproduces_the_profiles_of_random_trios(l50):
    rng = random.Random(1014)
    for trio in rng.sample(list(itertools.combinations(CLASS_CODES, 3)), 30):
        made = bundle(trio, 50, TABLES, RULES, l50)
        buffsets = buffsets_for(trio, 50, l50)
        race = rng.choice([entry["code"] for entry in made["races"]])
        role = rng.choice(roles.roles_for(trio))
        key = rng.choice(BUFF_SETS)
        assert assemble(made, race, role, key) == reference_dict(trio, 50, race, role, buffsets[key]), trio


def test_the_assembled_profiles_are_the_ones_the_precompute_pipeline_solves():
    codes = ("PAL", "MNK", "BER")
    config, meta = grid.load_inputs(codes, catalog_path=REPO / "derived" / "catalog.json")
    ctx = grid.Context(config)
    made = bundle(codes, config.level, TABLES, RULES, config.spells, data_release=meta.data_release)
    assert (made["data_release"], made["rules_version"]) == (meta.data_release, meta.rules_version)
    for key in ("own", "group"):
        listed = made["buffs"][key]["set"]
        assert listed["optional"] == [b.id for b in ctx.buffsets[key].optional]
        assert listed["always_on"] == [b.id for b in ctx.buffsets[key].always_on]
        for race, _ in grid.race_order(codes, TABLES):
            for role in roles.roles_for(codes):
                for label in ("strict", "wiki"):
                    got = assemble(made, race, role, key, evidence=label)
                    assert got == ctx.profile(race, role, key, label).to_dict(), (race, role, key, label)


@pytest.mark.parametrize("trio", FIVE_TRIOS[1:])
def test_the_assembled_profiles_of_the_other_trio_types_are_the_ones_the_precompute_pipeline_solves(trio):
    config, meta = grid.load_inputs(trio, catalog_path=REPO / "derived" / "catalog.json")
    ctx = grid.Context(config)
    made = bundle(trio, config.level, TABLES, RULES, config.spells, data_release=meta.data_release)
    for race, _ in grid.race_order(trio, TABLES):
        for role in roles.roles_for(trio):
            for label in ("strict", "wiki"):
                got = assemble(made, race, role, "own", evidence=label)
                assert got == ctx.profile(race, role, "own", label).to_dict(), (trio, race, role, label)


def test_a_level_55_bundle_reassembles_too(l55):
    trio = ("PAL", "MNK", "BER")
    made = bundle(trio, 55, TABLES, RULES, l55)
    buffsets = buffsets_for(trio, 55, l55)
    assert made["level"] == 55 and made["monk_bins"]["curve"]["softcap_stones"] == "20/1"
    for race in ("HUM", "IKS", "OGR"):
        for role in roles.roles_for(trio):
            for key in BUFF_SETS:
                assert assemble(made, race, role, key) == reference_dict(trio, 55, race, role, buffsets[key])


def test_the_evidence_label_and_the_deity_are_the_two_choices_assemble_takes_on_top(pmb, l50):
    trio, buffsets = ("PAL", "MNK", "BER"), buffsets_for(("PAL", "MNK", "BER"), 50, l50)
    wiki = assemble(pmb, "OGR", "tank", "group", evidence="wiki")
    assert wiki == reference_dict(trio, 50, "OGR", "tank", buffsets["group"], evidence="wiki")
    assert pmb["evidence_levels"] == ["strict", "wiki"] and pmb["profile_common"]["evidence"] == "strict"
    locked = assemble(pmb, "OGR", "tank", "group", deity="Tunare")
    assert locked == reference_dict(trio, 50, "OGR", "tank", buffsets["group"], deity="Tunare")
    with pytest.raises(ValueError, match="evidence"):
        assemble(pmb, "OGR", "tank", "group", evidence="hidden")
    with pytest.raises(ValueError, match="deity"):
        assemble(pmb, "OGR", "tank", "group", deity="  ")


@pytest.mark.parametrize(
    ("race", "role", "buffs", "word"),
    [("XXX", "tank", "own", "race"), ("OGR", "caster", "own", "role"), ("OGR", "tank", "party", "buffs")],
)
def test_assemble_refuses_what_the_bundle_does_not_have(pmb, race, role, buffs, word):
    with pytest.raises(ValueError, match=word):
        assemble(pmb, race, role, buffs)


def test_assemble_hands_out_copies_so_that_a_caller_cannot_change_the_bundle(pmb):
    before = copy.deepcopy(pmb)
    got = assemble(pmb, "HUM", "tank", "own")
    got["weights"]["HP"] = 99
    got["naked"]["STR"] = 1
    got["pools"]["HP"].clear()
    got["buff_totals"]["SV"] = None
    got["setups"].append("x")
    assert pmb == before


def test_the_profile_parts_are_split_by_what_varies_and_nothing_is_in_two_places(pmb):
    fields = [item.name for item in dataclasses.fields(Profile)]
    common, race_part, role_part, buff_part = (
        set(pmb["profile_common"]),
        {"race", "naked", "iksar_ac"},
        {"role", "weights", "setups"},
        {"buff_totals", "spell_haste"},
    )
    assert common | race_part | role_part | buff_part == {"format", *fields}
    assert not common & (race_part | role_part | buff_part)
    assert list(pmb["profile_common"]) == [f for f in ["format", *fields] if f in common]


# ---- races, roles and buffs ------------------------------------------------------------------------------------------


def test_the_races_come_in_the_order_of_the_pages_with_legality_and_the_racial_values(pmb):
    codes = ("PAL", "MNK", "BER")
    order = grid.race_order(codes, TABLES)
    assert [(r["code"], r["legal"]) for r in pmb["races"]] == order
    names = {entry["code"]: entry["name"] for entry in TABLES.races["races"]}
    for row in pmb["races"]:
        assert row["name"] == names[row["code"]]
        assert row["naked"] == fm.naked(row["code"], codes, TABLES)
        assert row["iksar_ac"] == (RULES.get("race.iksar_ac_bonus") if row["code"] == "IKS" else 0)
    assert [r["code"] for r in pmb["races"] if r["legal"]] == [c for c, legal in order if legal]
    assert any(not r["legal"] for r in pmb["races"])


def test_the_roles_are_the_offered_ones_with_their_weights_and_setups(pmb):
    codes = ("PAL", "MNK", "BER")
    assert list(pmb["roles"]) == roles.roles_for(codes) == ["balanced", "tank", "melee"]
    for role, row in pmb["roles"].items():
        assert set(row) == {"weights", "setups", "setups_by_evidence"}
        assert row["weights"] == roles.weights_for(codes, role, RULES, mana_reachable=True)
        assert row["setups"] == weapons.setups_for(codes, role, TABLES, level=50)  # no pool to read: a shield assumed
        assert list(row["setups_by_evidence"]) == pmb["evidence_levels"] == ["strict", "wiki"]
        for setups in row["setups_by_evidence"].values():
            assert [setup for setup in row["setups"] if setup in setups] == setups  # a pool can only take a setup away


def test_a_trio_with_one_role_has_balanced_only(l50):
    codes = ("WIZ", "MAG", "ENC")
    made = bundle(codes, 50, TABLES, RULES, l50)
    assert list(made["roles"]) == ["balanced"]
    assert made["roles"]["balanced"]["setups"] == weapons.setups_for(codes, "balanced", TABLES, level=50)
    assert "stick" in made["roles"]["balanced"]["setups"]
    assert made["monk_bins"] is None


@pytest.mark.parametrize("trio", FIVE_TRIOS)
def test_each_buff_key_holds_the_totals_the_spell_haste_and_the_resolved_set(trio, l50):
    made = bundle(trio, 50, TABLES, RULES, l50)
    buffsets = buffsets_for(trio, 50, l50)
    table = made["buff_table"]
    for key, buffset in buffsets.items():
        row = made["buffs"][key]
        assert row["buff_totals"] == eval_buffs(buffset.totals(()))
        assert row["spell_haste"] == max((b.haste for b in (*buffset.always_on, *buffset.optional)), default=0)
        listed = row["set"]
        assert listed["always_on"] == [b.id for b in buffset.always_on]
        assert listed["optional"] == [b.id for b in buffset.optional]
        assert listed["conflicts"] == [[a, b, list(why)] for (a, b), why in buffset.conflict_reasons]
        assert listed["cliques"] == [list(c) for c in buffset.cliques]
        assert listed["cardinality"] == buffset.cardinality
        assert listed["dropped"] == [[d.id, d.name, d.reason, d.by] for d in buffset.dropped]
        for buff in (*buffset.always_on, *buffset.optional):
            entry = table[str(buff.id)]
            assert entry["name"] == buff.name and entry["source"] == buff.source
            assert entry["vec"] == {c: v for c, v in zip(COMPONENTS, buff.vec) if v}
            assert entry["classes"] == dict(buff.classes)
            assert entry.get("illusion", False) == buff.illusion
    ids = [int(i) for i in table]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
    used = {i for row in made["buffs"].values() for part in ("always_on", "optional") for i in row["set"][part]}
    assert used == set(ids)


def test_the_enchanter_line_is_in_the_third_set_and_the_raid_holds_more_still(pmb):
    group, enchanted, raid = (pmb["buffs"][key] for key in ("group", "group+enchanter", "raid"))
    assert (group["spell_haste"], enchanted["spell_haste"], raid["spell_haste"]) == (40, 60, 60)
    assert enchanted != group
    assert raid["set"]["cardinality"] == 15 and len(raid["set"]["optional"]) > len(group["set"]["optional"])
    assert pmb["buffs"]["own"]["spell_haste"] <= group["spell_haste"]


def test_an_enchanter_trio_already_has_the_line_as_its_own(l50):
    made = bundle(("WIZ", "MAG", "ENC"), 50, TABLES, RULES, l50)
    assert made["buffs"]["own"]["spell_haste"] == made["buffs"]["group+enchanter"]["spell_haste"] == 60


# ---- the buff table holds whole numbers ------------------------------------------------------------------------------
#
# The browser checks that the always-on buffs of a set add up to the totals of the profile, in exact arithmetic; Python
# adds the same buffs as floats and compares the floats. The two agree for whole numbers, which is all the client files
# give (every scored effect of both spell files is a whole number), and could disagree for a fraction (0.1 + 0.2). So the
# bundle takes whole numbers only, and the writer refuses anything else.


@pytest.mark.parametrize("level", [50, 55])
def test_every_scored_value_of_a_spell_file_is_a_whole_number(level):
    from trioforge.model.buffs import SCORED_SPA, Buff

    records = spells_file(level)["spells"]
    values = [
        effect["value"] for record in records for effect in record["effects"]
        if effect["spa"] in SCORED_SPA and effect.get("value") is not None
    ]  # fmt: skip
    assert len(values) > 300
    assert all(type(value) is int for value in values)
    built = 0
    for record in records:
        try:
            buff = Buff.from_spell(record)
        except ValueError:  # an effect the model scores has no value: such a spell is never a buff
            continue
        assert all(type(amount) is int for amount in buff.vec), record["id"]
        built += 1
    assert built > 300


@pytest.mark.parametrize("trio", FIVE_TRIOS)
def test_every_component_of_every_buff_of_the_table_is_a_whole_number(trio, l50):
    made = bundle(trio, 50, TABLES, RULES, l50)
    seen = 0
    for entry in made["buff_table"].values():
        for name, amount in entry["vec"].items():
            assert name in COMPONENTS and type(amount) is int, (entry["name"], name, amount)
            seen += 1
    assert seen > 20


def scored_values_shifted(spells, by):
    """The spell file with every scored value moved by ``by`` (so that a buff has a fraction in it)."""
    from trioforge.model.buffs import SCORED_SPA

    moved = copy.deepcopy(spells)
    for record in moved["spells"]:
        for effect in record["effects"]:
            if effect["spa"] in SCORED_SPA and effect.get("value") is not None:
                effect["value"] = effect["value"] + by
    return moved


def test_a_bundle_of_a_buff_with_a_component_that_is_not_a_whole_number_is_refused(l50):
    shifted = scored_values_shifted(l50, 0.5)
    with pytest.raises(ValueError, match=r"buff \d+ \(.+\): [A-Z]+ is .*not a whole number"):
        bundle(("PAL", "MNK", "BER"), 50, TABLES, RULES, shifted)
    # the same shift by a whole number is a bundle
    assert bundle(("PAL", "MNK", "BER"), 50, TABLES, RULES, scored_values_shifted(l50, 1))["buff_table"]


def test_the_entry_of_a_buff_writes_whole_numbers_as_integers_and_refuses_the_rest(l50):
    buff = own_buffs(("PAL", "MNK", "BER"), 50, l50, RULES)[0]
    position = next(at for at, amount in enumerate(buff.vec) if amount)
    for amount, written in ((7, 7), (7.0, 7), (Fraction(14, 2), 7), (-3.0, -3)):
        vec = tuple(amount if at == position else 0 for at in range(len(buff.vec)))
        entry = browser._buff_entry(dataclasses.replace(buff, vec=vec))
        assert entry["vec"] == {COMPONENTS[position]: written} and type(entry["vec"][COMPONENTS[position]]) is int
    for bad in (0.1, -0.5, 2.0000001, Fraction(1, 3), math.inf, math.nan, True, "7", None, 2**53, 1e300, -(2**60)):
        vec = tuple(bad if at == position else 0 for at in range(len(buff.vec)))
        with pytest.raises(ValueError, match="not a whole number"):
            browser._buff_entry(dataclasses.replace(buff, vec=vec))


# ---- the constants ---------------------------------------------------------------------------------------------------


def test_every_number_outside_the_profile_parts_is_a_reduced_rational_string(pmb):
    seen = 0
    for block in RATIONAL_BLOCKS:
        for path, leaf in walk(pmb[block], block):
            assert not isinstance(leaf, float), path
            if isinstance(leaf, int) and not isinstance(leaf, bool):
                raise AssertionError(f"{path}: a bare integer ({leaf}); rationals are written as p/q")
            if isinstance(leaf, str) and RATIONAL.fullmatch(leaf):
                fraction = decode(leaf)
                assert leaf == f"{fraction.numerator}/{fraction.denominator}", path
                seen += 1
    assert seen > 300


def module_constants(module):
    """The names the module assigns at its top level in capitals (an import of a constant is not one of its own)."""
    names = set()
    for node in ast.parse(inspect.getsource(module)).body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        else:
            targets = [node.target] if isinstance(node, ast.AnnAssign) else []
        names |= {t.id for t in targets if isinstance(t, ast.Name) and re.fullmatch(r"[A-Z][A-Z_0-9]+", t.id)}
    return sorted(names)


def test_every_constant_of_the_formulas_module_is_exported_and_equal(pmb):
    names = module_constants(fm)
    assert {"STAT_CAP", "MANA_BANDS", "SHEET_ITEM_MULT", "STANDARD_CAPS"} <= set(names) and "MISSING" not in names
    missing = [name for name in names if name not in browser.FORMULA_CONSTANTS]
    assert not missing, f"constants of trioforge.model.formulas the bundle does not export: {missing}"
    assert set(browser.FORMULA_CONSTANTS) <= set(names)
    for name, dotted in browser.FORMULA_CONSTANTS.items():
        value = getattr(fm, name)
        if name in ("STA_CURVE", "MANA_BANDS"):
            value = {"breaks": value[0], "slopes": value[1]}
        elif name in ("WEIGHT_KEYS", "BUFF_KEYS", "ITEM_STATS", "PLACEMENTS"):
            value = sorted(value) if name != "PLACEMENTS" else list(value)
        assert decode(path_get(pmb["constants"], dotted)) == exact(value), (name, dotted)


def test_the_item_and_weapon_constants_are_exported_too(pmb):
    constants = pmb["constants"]
    assert [(n, int(decode(c))) for n, c in constants["slot_groups"]] == list(SLOT_GROUPS)
    assert constants["item_stat_order"] == [*items_module.STAT_KEYS, *items_module.REGEN_KEYS]
    assert constants["item_stats"] == sorted(fm.ITEM_STATS) == sorted(constants["item_stat_order"])
    assert constants["sv_keys"] == list(items_module.SV_KEYS)
    assert constants["buff_components"] == list(COMPONENTS)
    assert constants["weapon_setups"] == list(weapons.SETUPS)
    exported = {
        "BONUS_ONE_HANDED": "weapon_index.bonus_one_handed",
        "BONUS_TWO_HANDED": "weapon_index.bonus_two_handed",
        "DUAL_WIELD_FACTOR": "weapon_index.dual_wield_factor_default",
    }
    for name, dotted in exported.items():
        assert decode(path_get(constants, dotted)) == exact(getattr(weapons, name)), name


def test_the_rule_driven_constants_come_from_the_rules_for_the_level(pmb):
    constants = pmb["constants"]
    assert decode(constants["regen_caps"]) == exact(RULES.get("regen.gear_caps"))
    assert decode(constants["resist_cap"]) == RULES.get("resist.cap")
    assert decode(constants["haste"]) == {
        "cap": RULES.get("haste.cap_pct"), "cap_with_monk": RULES.get("haste.cap_pct_with_monk"),
        "worn_per_tier": RULES.get("haste.worn_per_tier"),
    }  # fmt: skip
    assert decode(constants["iksar_ac_bonus"]) == RULES.get("race.iksar_ac_bonus")
    steps = RULES.get("ac.softcap.combat_stability_pct")
    assert decode(constants["aa"]["combat_stability_pct"]) == {rank: Fraction(pct) for rank, pct in steps.items()}
    assert decode(constants["aa"]["physical_enhancement_pct"]) == RULES.get("ac.softcap.physical_enhancement_pct")
    assert constants["aa"]["pe_for_caster_only_trios"] is RULES.get("ac.softcap.pe_for_caster_only_trios")
    assert constants["mana_stat_by_class"] == RULES.get("mana.stat_by_class")


def test_the_softcap_rows_are_those_of_the_trios_classes_at_the_level(pmb):
    rows = pmb["constants"]["softcap_rows"]
    assert list(rows) == ["PAL", "MNK", "BER"]
    for code, row in rows.items():
        cap, rate = TABLES.softcap[(code, 50)]
        assert decode(row) == {"cap": exact(cap), "rate": exact(rate)}
    best = max(rows.values(), key=lambda row: (decode(row["cap"]), decode(row["rate"])))
    assert (decode(best["cap"]), float(decode(best["rate"]))) == tuple(pmb["profile_common"]["softcap"])


# ---- the Monk bonus per whole stone ----------------------------------------------------------------------------------


def test_the_monk_bins_are_the_bonus_of_every_whole_stone_as_rationals(pmb):
    monk = pmb["monk_bins"]
    curve = fm.monk_curve(RULES, 50)
    assert decode(monk["curve"]) == {**{k: Fraction(v) for k, v in curve.items()}, "shape": "EQEmu fade"}
    bins = decode(monk["bonus"])
    assert all(isinstance(b, Fraction) and b.denominator == 1 for b in bins)
    for stones, bonus in enumerate(bins):
        assert bonus == fm.monk_bonus(50, 10 * stones, curve), stones
    last = len(bins) - 1
    assert last >= curve["hardcap_stones"] + 90  # the penalty has stopped growing
    for extra in (1, 2, 7, 50, 400):
        assert fm.monk_bonus(50, 10 * (last + extra), curve) == bins[-1]
    assert bins[0] == bins[curve["softcap_stones"]] == 73 and bins[-1] < 0


def test_the_alternative_monk_curve_is_exported_as_its_own_bins(pmb):
    (alternative,) = pmb["monk_bins"]["alternatives"]
    curve = {**fm.monk_curve(RULES, 50), **RULES.alternatives("monk.weight_curve")[0]["value"]}
    assert decode(alternative["curve"])["full_until_stones"] == 34
    bins = decode(alternative["bonus"])
    for stones, bonus in enumerate(bins):
        assert bonus == fm.monk_bonus(50, 10 * stones, curve), stones
    assert bins[34] == 73 and bins[35] != 73


def _monk_rules_at(level, softcap, hardcap):
    """The rules with a Monk curve of the given stones at ``level``, whose full bonus is the one that level gives."""
    raw = copy.deepcopy(RAW_RULES)
    (rule,) = [rule for rule in raw["rules"] if rule["id"] == "monk.weight_curve"]
    rule["levels"] = {
        str(level): {
            "softcap_stones": softcap,
            "hardcap_stones": hardcap,
            "full_bonus_ac": int((4.0 * (level + 5.0)) / 3.0),
            "shape": fm.MONK_SHAPE,
        }
    }
    return Rules(raw)


def test_the_last_bin_of_every_monk_table_is_the_bonus_of_every_weight_past_it():
    """The browser takes the last bin for a weight beyond the table, so the table must run to where the penalty has stopped growing:
    ``hardcap_stones`` and 100 more, for the curve and for each alternative, at every level, for each curve of the rules file."""
    (rule,) = [rule for rule in RAW_RULES["rules"] if rule["id"] == "monk.weight_curve"]
    curves = sorted({(value["softcap_stones"], value["hardcap_stones"]) for value in [rule["value"], *rule["levels"].values()]})
    assert len(curves) == 2  # the curve of the rules file and the one of level 55
    tables = 0
    for level in range(1, 61):
        for softcap, hardcap in curves:
            written = browser.monk_bins(level, _monk_rules_at(level, softcap, hardcap))
            assert len(written["alternatives"]) == 1  # the alternative reading, "the full bonus up to 34 stones"
            for block in (written, *written["alternatives"]):
                curve = {key: int(value) for key, value in decode(block["curve"]).items() if key != "shape"}
                bins = decode(block["bonus"])
                assert curve["hardcap_stones"] == hardcap and curve["full_bonus_ac"] == int((4.0 * (level + 5.0)) / 3.0)
                assert len(bins) == hardcap + 100 + 1, (level, softcap, hardcap)
                last = len(bins) - 1
                for stones in range(last, last + 201):  # from the last stone of the table to 200 stones past it
                    assert fm.monk_bonus(level, 10 * stones, curve) == bins[-1], (level, softcap, hardcap, stones, curve)
                tables += 1
    assert tables == 60 * len(curves) * 2
    for level in (50, 55):  # and the bins of the rules file itself, at the two levels it has a curve for
        written = browser.monk_bins(level, RULES)
        for block in (written, *written["alternatives"]):
            curve = {key: int(value) for key, value in decode(block["curve"]).items() if key != "shape"}
            bins = decode(block["bonus"])
            assert len(bins) == curve["hardcap_stones"] + 100 + 1
            assert all(fm.monk_bonus(level, 10 * stones, curve) == bins[-1] for stones in range(len(bins) - 1, len(bins) + 200))


def test_a_trio_without_a_monk_has_no_bins(l50):
    assert bundle(("WAR", "ROG", "BER"), 50, TABLES, RULES, l50)["monk_bins"] is None


# ---- tier rules, weapon rules, weights and regen ---------------------------------------------------------------------


def test_the_tier_rules_are_what_at_tier_reads(pmb):
    tier = decode(pmb["tier_rules"])
    assert tier["max_tier"] == items_module.MAX_TIER == 10
    assert tier["stat_rule"] == RULES.get("tier.stat_rule") == items_module.STAT_RULE_TEXT
    assert tier["negatives_scale"] is False
    assert tier["weight_floor10"] == 1 and tier["unknown_weight10"] == items_module.UNKNOWN_WEIGHT10
    assert tier["haste_per_tier"] == RULES.get("haste.worn_per_tier")
    assert tier["regen_per_tier"] == RULES.get("regen.per_tier")
    assert tier["accuracy_pct"] == fm.fr(RULES.get("tier.accuracy_pct")) == Fraction(5, 2)
    assert tier["socket_open"] == RULES.get("tier.socket_open")
    assert tier["max_fresh_drop"] == RULES.get("tier.max_fresh_drop") == 4
    assert tier["exp_needed"] == RULES.get("tier.exp_needed")
    assert tier["tier_rule_values"] == ["drop", "fixed0", "spell"]
    assert tier["arrival"] == RULES.get("tier.arrival")


def test_the_exported_tier_numbers_are_the_ones_at_tier_applies(pmb):
    tier = decode(pmb["tier_rules"])
    divisor, floor10, top = int(tier["stat_divisor"]), int(tier["weight_floor10"]), int(tier["max_tier"])

    def probe(stats, weight=1.0):
        return {
            "key": "w1", "name": "Probe", "slots": ["HEAD"], "classes": ["ALL"], "deity": None, "flags": [],
            "stats": stats, "sv": {}, "weight": weight, "weapon": None,
        }  # fmt: skip

    for base in range(1, 120):
        for n in range(top + 1):
            grown = at_tier(probe({"HP": base}), n, RULES).stats["HP"]
            assert grown == base + max(n, base * n // divisor), (base, n)
    for n in range(top + 1):
        got = at_tier(probe({"HASTE": 10, "HPREG": 3, "STR": -5}), n, RULES)
        assert got.haste == 10 + n * int(tier["haste_per_tier"])
        assert got.stats["HPREG"] == 3 + n * int(tier["regen_per_tier"])
        assert got.stats["STR"] == -5  # a negative stat does not scale
    assert at_tier(probe({}, 0.3), top, RULES).weight10 == floor10
    unknown = at_tier(probe({}, None), 0, RULES)
    assert (unknown.weight10, unknown.weight_known) == (int(tier["unknown_weight10"]), False)


def test_the_weapon_rules_label_the_switch_and_name_both_rates(pmb):
    weapon = decode(pmb["weapon_rules"])
    assert weapon["damage_pct"] == 5 and weapon["damage_pct_choices"] == [5, 10]
    assert weapon["test"] == RULES.settled_by("tier.weapon_damage_pct") == "B5"
    assert weapon["seal"] == RULES.seal("tier.weapon_damage_pct")
    assert weapon["delay_changes"] is False and "dmg" in weapon["damage_rule"]
    assert weapon["damage_weight"] == RULES.get("weapons.damage_weight") == 600
    assert weapon["dual_wield_factor"] == fm.fr(RULES.get("weapons.dual_wield_factor"))
    assert weapon["bonus_one_handed"] == Fraction(1, 2) == fm.fr(weapons.BONUS_ONE_HANDED)
    assert weapon["bonus_two_handed"] == Fraction(67, 100) == fm.fr(weapons.BONUS_TWO_HANDED)
    assert weapon["label"] == "Weapon damage per tier"
    assert weapon["setups"] == list(weapons.SETUPS)


def test_the_damage_rule_text_gives_the_damage_the_tiers_give(pmb):
    # dmg + max(n, dmg * n * pct // 100) for both rates: the rule the export names is the one at_tier applies
    weapon = {"skill": "1H Slashing", "dmg": 100, "delay": 40, "bonus": None}
    item = {
        "key": "w1", "name": "Probe", "slots": ["PRIMARY"], "classes": ["ALL"], "deity": None, "flags": [], "stats": {},
        "sv": {}, "weight": 1.0, "weapon": weapon,
    }  # fmt: skip
    for pct in decode(pmb["weapon_rules"])["damage_pct_choices"]:
        for n in range(11):
            assert at_tier(item, n, RULES, weapon_pct=int(pct)).weapon.dmg == 100 + max(n, 100 * n * int(pct) // 100)
            assert at_tier(item, n, RULES, weapon_pct=int(pct)).weapon.delay == 40


def test_the_weight_groups_are_the_roles_module_s_with_the_three_positions(pmb):
    groups = pmb["weight_groups"]
    assert groups["groups"] == {name: list(keys) for name, keys in roles.WEIGHT_GROUPS.items()}
    assert decode(groups["multipliers"]) == [Fraction(1, 2), 1, 2]
    assert groups["custom_keys"] == list(roles.CUSTOM_KEYS)
    assert groups["derived"] == ["DMG", "HPREG", "MANAREG", "ENDREG"] == list(roles.DERIVED_KEYS)
    assert groups["damage_follows"] == "ATK" and groups["mana_keys"] == ["MANA", "MANAREG"]
    assert groups["regen_sources"] == {"HPREG": "HP", "MANAREG": "MANA", "ENDREG": "END"}
    assert decode(groups["custom_max"]) == roles.CUSTOM_MAX and decode(groups["regen_t_max"]) == roles.REGEN_T_MAX


def test_the_regen_inputs_are_integer_ratios(pmb):
    ratios = pmb["regen_ratios"]
    assert ratios == {
        "ticks_per_minute": "10/1", "default_minutes": "3/1", "max_minutes": "60/1", "match": "1/1000000000000"
    }  # fmt: skip


def test_a_regen_window_that_is_not_whole_is_a_reduced_ratio_of_integers(l50):
    data = copy.deepcopy(RAW_RULES)
    for rule in data["rules"]:
        if rule["id"] == "regen.value_minutes":
            rule["value"] = 1.5
    other = Rules(data)
    tables = dataclasses.replace(TABLES, rules=other)
    made = bundle(("PAL", "MNK", "BER"), 50, tables, other, l50)
    assert made["regen_ratios"]["default_minutes"] == "3/2"
    assert made["roles"]["tank"]["weights"]["HPREG"] == 15  # 10 ticks a minute x 1.5 minutes x the HP weight of 1


# ---- the item table: what it holds -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def catalog_doc():
    return loads_strict((REPO / "derived" / "catalog.json").read_text(encoding="utf-8"), "catalog.json")


@pytest.fixture(scope="module")
def table(catalog_doc):
    return items(catalog_doc, RULES)


MODEL_SLOTS = frozenset(name for name, _ in SLOT_GROUPS)


def wearable(item):
    return bool(MODEL_SLOTS & set(item["slots"]))


def key_of(record):
    return record.get("key") or f"w{record['id']}"


def test_the_table_has_a_header_and_one_record_for_every_wearable_of_the_catalog(table, catalog_doc):
    assert table["version"] == 1 and table["rules_version"] == RULES.version
    assert table["data_release"] == f"data-{catalog_doc['version']}"
    wearables = [item for item in catalog_doc["items"] if wearable(item)]
    assert table["count"] == len(table["items"]) == len(wearables) > 6000
    by_page = sorted(wearables, key=lambda item: item["wiki"]["pageid"])
    assert [key_of(r) for r in table["items"]] == [item["key"] for item in by_page]
    listed = {key_of(r) for r in table["items"]}
    assert not any(i["key"] in listed for i in catalog_doc["items"] if not wearable(i))


@pytest.fixture(scope="module")
def after_an_add(tmp_path_factory, catalog_doc):
    """The catalog once reports have been accepted for a live wearable (strict now) and for two that the wiki or the zones outweigh."""
    return AfterAnAdd(tmp_path_factory.mktemp("after-an-add"), catalog_doc)


@pytest.mark.parametrize("after", [False, True], ids=["the committed catalog", "the catalog after an accepted report"])
def test_hidden_wearables_are_in_the_table_flagged_owned_only_and_nothing_else_is(request, after):
    if after:
        catalog_doc = request.getfixturevalue("after_an_add").document
        table = items(catalog_doc, RULES)
    else:
        catalog_doc, table = request.getfixturevalue("catalog_doc"), request.getfixturevalue("table")
    level = {i["key"]: i["evidence"]["level"] for i in catalog_doc["items"]}
    flagged = {key_of(r) for r in table["items"] if r.get("owned_only")}
    assert flagged == {key_of(r) for r in table["items"] if level[key_of(r)] == "hidden"}
    assert 3000 < len(flagged) < len(table["items"])
    assert all(r["evidence"]["level"] == level[key_of(r)] for r in table["items"])
    shown = {r["evidence"]["level"] for r in table["items"] if not r.get("owned_only")}
    assert shown - {"strict"} == {"wiki", "disputed"}  # (and strict, for the items that a report made strict, which is public)
    assert strict_without_a_report(table) == [] and ("strict" in shown or not after)  # (the catalog after a report has a strict item: the setup holds)


def test_the_records_are_sorted_by_the_numeric_page_id(table):
    ids = [r["id"] for r in table["items"]]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert ids != sorted(ids, key=str)  # not the order of the text


def test_every_record_carries_what_at_tier_reads_so_the_item_comes_back_exactly(table, catalog_doc):
    originals = {i["key"]: i for i in catalog_doc["items"]}
    defaults = table["defaults"]
    for record in table["items"]:
        rebuilt = browser.item_to_catalog(record, defaults)
        original = originals[key_of(record)]
        for tier in (0, 1, 4, 10):
            for pct in (5, 10):
                got = at_tier(rebuilt, tier, RULES, weapon_pct=pct)
                assert got == at_tier(original, tier, RULES, weapon_pct=pct), (key_of(record), tier, pct)


def test_the_weight_is_an_integer_number_of_tenths_of_a_stone_or_null_when_the_page_has_none(table, catalog_doc):
    originals = {i["key"]: i for i in catalog_doc["items"]}
    unknown = 0
    for record in table["items"]:
        weight = originals[key_of(record)]["weight"]
        if weight is None:
            assert record["weight10"] is None
            unknown += 1
        else:
            assert type(record["weight10"]) is int and record["weight10"] == items_module._tenths(weight)
    assert unknown == 7


def test_records_keep_the_tier_rule_the_item_type_and_where_it_came_from(table, catalog_doc):
    originals = {i["key"]: i for i in catalog_doc["items"]}
    shields = 0
    for record in table["items"]:
        original = originals[key_of(record)]
        assert record["tier_rule"] == original["tier_rule"]
        assert record.get("item_type") == original["item_type"]
        assert record.get("item_type_source") == original["item_type_source"]
        assert record.get("deity") == original["deity"] and record.get("races", ["ALL"]) == original["races"]
        shields += record.get("item_type") == "Shield"
    assert shields > 100


def test_evidence_keeps_the_level_and_the_reason_codes_without_their_details_or_texts(table, catalog_doc):
    originals = {i["key"]: i for i in catalog_doc["items"]}
    for record in table["items"]:
        reasons = originals[key_of(record)]["evidence"]["reasons"]
        codes = sorted({reason["code"].split(":")[0] for reason in reasons})
        shown = record["evidence"].get("codes", [])
        assert set(shown) <= set(codes)
        notes = {"not-for-bis", "not-for-default-kits"}
        assert notes & set(codes) == notes & set(shown)  # the two notes the pools care about always survive
        assert all(":" not in code for code in shown)
        assert set(record["evidence"]) <= {"level", "codes"}  # no reason text, no seal


def test_a_farm_target_has_a_source_summary_and_a_hidden_item_has_none(table, catalog_doc):
    originals = {i["key"]: i for i in catalog_doc["items"]}
    with_source = 0
    for record in table["items"]:
        if record.get("owned_only"):
            assert "source" not in record
            continue
        sources = originals[key_of(record)]["sources"]
        summary = record.get("source", {})
        assert set(summary) <= {"drops", "sold", "quests", "crafted", "forage", "more"}
        zones = {d["zone"] for d in sources["drops"] if d["zone"]}
        if zones:
            assert summary["drops"] and set(summary["drops"]) <= zones and len(summary["drops"]) <= 3
            assert len(summary["drops"]) + summary.get("more", {}).get("drops", 0) == len(zones)
        if sources["crafted"]:
            assert summary["crafted"] == len(sources["crafted"])
        with_source += bool(summary)
    assert with_source > 1000


def test_the_table_is_plain_json_the_same_every_time_and_within_the_size_budget(table, catalog_doc):
    again = items(catalog_doc, RULES)
    text = json.dumps(table, separators=(",", ":"), allow_nan=False)
    assert json.dumps(again, separators=(",", ":")) == text
    assert len(text.encode()) <= 2_000_000  # the budget for the item table: 2 MB raw, 300 KB gzip
    assert len(gzip.compress(text.encode(), 9)) <= 300_000


def test_a_bare_list_of_items_is_a_catalog_too(catalog_doc):
    few = catalog_doc["items"][:50]
    from_list, wrapped = items(few, RULES), items({"version": "2030-01-02", "items": few}, RULES)
    assert [key_of(r) for r in from_list["items"]] == [key_of(r) for r in wrapped["items"]]
    assert from_list["data_release"] is None and wrapped["data_release"] == "data-2030-01-02"


# ---- the item table: ordering, names, aliases on small catalogs ------------------------------------------------------


def cat_item(pageid, title, **changes):
    """A catalog item with invented contents, as the catalog builder writes one."""
    base = {
        "key": f"w{pageid}", "name": title, "wiki": {"pageid": pageid, "revid": 1, "title": title},
        "slots": ["HEAD"], "classes": ["ALL"], "races": ["ALL"], "deity": None, "flags": [], "stats": {"AC": 3},
        "sv": {}, "weight": 1.0, "size": "SMALL", "item_type": None, "item_type_source": None, "weapon": None,
        "container_capacity": None, "instrument_mods": {}, "effects": [], "required_level": None,
        "recommended_level": None, "sources": {"drops": [], "sold_by": [], "quests": [], "crafted": []},
        "categories": [], "era_tags": [], "lucy_img_id": None, "tier_rule": "drop", "parse_warnings": [],
        "parse_warnings_overflow": 0, "evidence": {"level": "wiki", "reasons": []},
    }  # fmt: skip
    base.update(changes)
    return base


def test_the_order_is_by_the_number_of_the_page_not_by_its_text():
    catalog = [cat_item(n, f"Item {n}") for n in (100, 9, 10, 2, 33, 1000)]
    assert [r["id"] for r in items(catalog, RULES)["items"]] == [2, 9, 10, 33, 100, 1000]


def test_an_item_without_a_page_number_goes_last_in_the_order_of_its_key():
    odd = [cat_item(5, "Five"), cat_item(1, "One")]
    for key in ("rzed", "rabc"):
        extra = cat_item(1, key, key=key)
        extra["wiki"] = {"pageid": None, "revid": None, "title": key}
        odd.append(extra)
    got = items(odd, RULES)["items"]
    assert [key_of(r) for r in got] == ["w1", "w5", "rabc", "rzed"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Chestguard", "Chestguard"),
        ("Gold Ring (Ring of Opolla)", "Gold Ring"),
        ("Band of (Fire) (RoF)", "Band of (Fire)"),
        ("X (Level 90 required)", "X"),
        ("Plain (Fire) Band", "Plain (Fire) Band"),
        ("Foo (Bar (Baz))", "Foo"),
        ("Foo (Bar", "Foo (Bar"),
        ("Foo Bar)", "Foo Bar)"),
        ("(Only)", "(Only)"),
        ("  (Only)", "(Only)"),
        ("Dusty Tunic*", "Dusty Tunic*"),
        ("Tunic* (Old)", "Tunic*"),
        ("A Yellow Whip", "A Yellow Whip"),
        ("Two  Spaces (Note)", "Two  Spaces"),
        ("Odd(NoSpace)", "Odd"),
        ("Empty ()", "Empty"),
    ],
)
def test_the_match_name_drops_one_trailing_parenthetical_and_nothing_else(title, expected):
    assert match_name(title) == expected


def effective(record):
    return record.get("match_name") or record["name"]


def test_titles_that_differ_only_by_a_trailing_parenthetical_share_one_match_name():
    catalog = [
        cat_item(1, "Gold Ring"), cat_item(2, "Gold Ring (Ring of Opolla)"), cat_item(3, "Gold Ring (Other)"),
        cat_item(4, "Stein"), cat_item(5, "Stein (of Water)"), cat_item(6, "Other Thing (Gold Ring)"),
        cat_item(7, "Lone Helm"),
    ]  # fmt: skip
    table = items(catalog, RULES)
    names = {key_of(r): effective(r) for r in table["items"]}
    assert names["w1"] == names["w2"] == names["w3"] == "Gold Ring"
    assert names["w4"] == names["w5"] == "Stein"
    assert names["w6"] == "Other Thing" and names["w7"] == "Lone Helm"
    # so a dump row "Gold Ring" or "Stein" matches several items: the matcher can only call it ambiguous
    assert browser.shared_match_names(table) == {"Gold Ring": ["w1", "w2", "w3"], "Stein": ["w4", "w5"]}
    assert browser.shared_match_names(table["items"]) == browser.shared_match_names(table)


def test_shared_match_names_are_by_name_in_table_order_and_only_those_with_more_than_one_item():
    odd = cat_item(9, "Shown (A)", wiki={"pageid": 9, "revid": 1, "title": "Same (A)"})
    plain = cat_item(2, "Same")
    far = cat_item(30, "Same (B)", key="rfar")
    table = items([odd, plain, far, cat_item(1, "Alone")], RULES)
    assert browser.shared_match_names(table) == {"Same": ["w2", "w9", "rfar"]}  # in the order of the page numbers
    assert browser.record_key({"id": 5}) == "w5" and browser.record_key({"id": 5, "key": "rx"}) == "rx"
    assert browser.effective_match_name({"name": "A (B)", "match_name": "A"}) == "A"
    assert browser.effective_match_name({"name": "A"}) == "A"


def test_in_the_real_export_every_title_and_its_parenthetical_forms_share_one_match_name(table, catalog_doc):
    # the real titles hold at most one flat group, so a plain pattern does the job without sharing code with match_name
    trailing = re.compile(r"\s*\([^()]*\)\s*$")
    by_title = {}
    for item in catalog_doc["items"]:
        if wearable(item):
            by_title.setdefault(item["wiki"]["title"], []).append(item["key"])
    records = {key_of(r): r for r in table["items"]}
    shared = browser.shared_match_names(table)
    pairs = 0
    for title, keys in by_title.items():
        if not trailing.search(title):
            continue
        base = trailing.sub("", title)
        for base_key in by_title.get(base, ()):
            for key in keys:
                assert effective(records[key]) == effective(records[base_key]) == base, (title, base)
                assert {key, base_key} <= set(shared[base]), (title, base)
                pairs += 1
    assert pairs >= 30  # "Gold Ring (Ring of Opolla)" and "Gold Ring", an "(Imbued)" piece and its plain base, ...
    assert "Gold Ring" in shared and "Silver Ring" in shared


def test_the_shared_match_names_of_the_real_export_are_consistent_and_counted(table):
    shared = browser.shared_match_names(table)
    assert 50 < len(shared) < 400
    assert list(shared) == sorted(shared)
    listed = [key for keys in shared.values() for key in keys]
    assert len(listed) == len(set(listed)) and all(len(keys) >= 2 for keys in shared.values())
    by_key = {key_of(r): effective(r) for r in table["items"]}
    assert all(by_key[key] == name for name, keys in shared.items() for key in keys)
    distinct = len({effective(r) for r in table["items"]})
    singles = sum(1 for r in table["items"] if effective(r) not in shared)
    assert distinct == len(shared) + singles and len(table["items"]) == len(listed) + singles
    assert max(len(keys) for keys in shared.values()) >= 3  # the families the wiki tells apart by a note in parentheses


def test_match_name_never_returns_an_empty_name():
    for title in ("(Only)", "()", " (a) ", "((x))"):
        assert match_name(title)


def test_records_carry_match_name_only_when_it_differs_from_the_display_name():
    catalog = [cat_item(1, "Plain Ring"), cat_item(2, "Gold Ring (Ring of Opolla)")]
    one, two = items(catalog, RULES)["items"]
    assert "match_name" not in one and two["match_name"] == "Gold Ring" and two["name"] == "Gold Ring (Ring of Opolla)"


def test_the_match_name_comes_from_the_wiki_title_not_the_display_name():
    odd = cat_item(7, "Display Name", wiki={"pageid": 7, "revid": 1, "title": "Shown (Variant)"})
    (record,) = items([odd], RULES)["items"]
    assert record["name"] == "Display Name" and record["match_name"] == "Shown"
    bare = cat_item(8, "Other", wiki={"pageid": 8, "revid": 1, "title": "Shown (X) (Y)"})
    assert items([bare], RULES)["items"][0]["match_name"] == "Shown (X)"


def test_aliases_come_from_a_table_by_key_and_are_clean():
    catalog = [cat_item(1, "Plain Ring"), cat_item(2, "Other Ring")]
    got = items(catalog, RULES, aliases={"w1": ["The Plain Ring", "Plain Ring", "Plain  Band", "Plain Band"]})["items"]
    # sorted, no repeat, and not the name itself
    assert got[0]["aliases"] == ["Plain  Band", "Plain Band", "The Plain Ring"]
    assert "aliases" not in got[1]
    for bad in ({"w1": "Plain"}, {"w1": [""]}, {"w1": [3]}, {"w9": ["Ghost"]}, [("w1", ["x"])]):
        with pytest.raises(ValueError, match="alias"):
            items(catalog, RULES, aliases=bad)


def test_an_item_with_no_evidence_is_refused_because_the_catalog_was_not_built():
    bare = cat_item(1, "Bare")
    del bare["evidence"]
    with pytest.raises(ValueError, match="evidence"):
        items([bare], RULES)


def test_only_the_slots_of_the_model_make_an_item_wearable():
    catalog = [
        cat_item(1, "Head", slots=["HEAD"]), cat_item(2, "Ammo", slots=["AMMO"]), cat_item(3, "Charm", slots=["CHARM"]),
        cat_item(4, "None", slots=[]), cat_item(5, "Mixed", slots=["AMMO", "RANGE"]),
    ]  # fmt: skip
    assert [r["id"] for r in items(catalog, RULES)["items"]] == [1, 5]


def test_a_weapon_keeps_the_four_fields_at_tier_reads_and_a_zero_weight_is_zero_tenths():
    weapon = {"skill": "1H Slashing", "dmg": 11, "delay": 30, "bonus": None, "backstab": 5}
    heavy = cat_item(1, "Blade", slots=["PRIMARY"], weapon=weapon, weight=0.04, flags=["lore"], deity=["Tunare"])
    (record,) = items([heavy], RULES)["items"]
    assert record["weapon"] == {"skill": "1H Slashing", "dmg": 11, "delay": 30, "bonus": None}
    assert record["weight10"] == 0 and record["lore"] is True and record["deity"] == ["Tunare"]
    rebuilt = browser.item_to_catalog(record, items([heavy], RULES)["defaults"])
    assert at_tier(rebuilt, 4, RULES) == at_tier(heavy, 4, RULES)


def test_the_defaults_of_a_table_are_a_copy_and_item_to_catalog_falls_back_to_the_module_s():
    small = items([cat_item(1, "Any")], RULES)
    small["defaults"]["classes"].append("WAR")
    assert browser.ITEM_DEFAULTS["classes"] == ["ALL"]
    assert items([cat_item(1, "Any")], RULES)["defaults"]["classes"] == ["ALL"]
    record = {"id": 5, "name": "Plain", "slots": ["HEAD"], "weight10": 12, "tier_rule": "drop"}
    rebuilt = browser.item_to_catalog(record)
    assert rebuilt == browser.item_to_catalog(record, browser.ITEM_DEFAULTS)
    assert (rebuilt["key"], rebuilt["classes"], rebuilt["weight"], rebuilt["deity"]) == ("w5", ["ALL"], 1.2, None)
    record["slots"].append("NECK")
    assert rebuilt["slots"] == ["HEAD"]  # the rebuilt item does not share the record's lists


def test_the_defaults_name_what_an_absent_field_means(table):
    assert table["defaults"] == {
        "key": None, "match_name": None, "classes": ["ALL"], "races": ["ALL"], "deity": None, "lore": False,
        "stats": {}, "sv": {}, "weapon": None, "item_type": None, "item_type_source": None, "aliases": [],
        "owned_only": False,
    }  # fmt: skip


# ---- the weapon setups follow the solve pool of each evidence level --------------------------------------------------
# The strict pool is the strict items and the wiki pool the strict and the wiki items (no deity-locked item in either).
# The shield setup is there only if the pool has a shield that a class of the trio can wear, so a level can lack it
# where the other has it, and the bundle lists the setups of each level the way the precompute makes them.

PBM = ("PAL", "MNK", "BER")
WITH_SHIELD, WITHOUT_SHIELD = ["1h-shield", "2h", "dw"], ["2h", "dw"]


def levelled(pageid, level, **changes):
    """An invented catalog item at an evidence level."""
    return cat_item(pageid, f"Item {pageid}", evidence={"level": level, "reasons": []}, **changes)


def shield(pageid, level, **changes):
    """An invented shield: it fits the off hand and says Shield; every class may wear it unless ``changes`` say not."""
    base = {"slots": ["SECONDARY"], "item_type": "Shield", "item_type_source": "statsblock"}
    return cat_item(pageid, f"Shield {pageid}", evidence={"level": level, "reasons": []}, **{**base, **changes})


def write_catalog(directory, listed, name="catalog.json"):
    path = directory / name
    path.write_text(json.dumps({"version": "2030-01-02", "items": listed}), encoding="utf-8")
    return path


# the items of a small catalog, and whether the strict pool and the wiki pool of it have a shield the trio can wear
POOLS = {
    "a shield of the wiki level": ([levelled(1, "strict"), shield(2, "wiki")], False, True),
    "a strict shield is in both pools": ([shield(2, "strict")], True, True),
    "a shield no class of the trio may wear": ([shield(2, "wiki", classes=["WIZ"])], False, False),
    "a shield locked to a deity is in no solve pool": ([shield(2, "strict", deity=["Tunare"])], False, False),
    "a hidden shield is in no solve pool": ([shield(2, "hidden")], False, False),
    "a catalog with no shield at all": ([levelled(1, "strict"), levelled(3, "wiki")], False, False),
    "a catalog with no items": ([], False, False),
}


def setups_wanted(role, shield_in_pool):
    return WITH_SHIELD if shield_in_pool and role != "melee" else WITHOUT_SHIELD  # Melee never plays 1H + shield


@pytest.mark.parametrize("case", POOLS)
def test_each_evidence_level_lists_the_setups_its_own_pool_allows(case, tmp_path):
    listed, in_strict, in_wiki = POOLS[case]
    config, meta = grid.load_inputs(PBM, catalog_path=write_catalog(tmp_path, listed))
    made = bundle(PBM, config.level, TABLES, RULES, config.spells, data_release=meta.data_release, catalog=listed)
    for role in roles.roles_for(PBM):
        assert made["roles"][role]["setups_by_evidence"] == {
            "strict": setups_wanted(role, in_strict), "wiki": setups_wanted(role, in_wiki)
        }, (case, role)  # fmt: skip
    # they are the setups the grid solves for each level, and the profiles the precompute makes
    ctx = grid.Context(config)
    pools = {kind: grid.shield_pool(config, RULES, kind) for kind in grid.EVIDENCE}
    plan = grid.scenarios(PBM, TABLES, RULES, races=["HUM"], tiers=[0], buffs=["own"], items=pools)
    for label in ("strict", "wiki"):
        for role in roles.roles_for(PBM):
            solved = [s.setup for s in plan if (s.evidence, s.role) == (label, role)]
            assert solved == made["roles"][role]["setups_by_evidence"][label], (case, label, role)
            for race, _ in grid.race_order(PBM, TABLES):
                for key in ("own", "group"):
                    got = assemble(made, race, role, key, evidence=label)
                    assert got == ctx.profile(race, role, key, label).to_dict(), (case, race, role, key, label)


def test_assemble_picks_the_setups_of_the_evidence_level_and_assumes_a_shield_without_one(l50):
    made = bundle(PBM, 50, TABLES, RULES, l50, catalog=[levelled(1, "strict"), shield(2, "wiki")])
    for role in ("balanced", "tank"):
        assert assemble(made, "HUM", role, "own", evidence="strict")["setups"] == WITHOUT_SHIELD
        assert assemble(made, "HUM", role, "own", evidence="wiki")["setups"] == WITH_SHIELD
        assert assemble(made, "HUM", role, "own")["setups"] == WITH_SHIELD  # no pool to read: as with no items
    assert assemble(made, "HUM", "melee", "own", evidence="wiki")["setups"] == WITHOUT_SHIELD
    with pytest.raises(ValueError, match="evidence"):
        assemble(made, "HUM", "tank", "own", evidence="hidden")


def test_assemble_with_an_evidence_level_hands_out_copies_too(l50):
    made = bundle(PBM, 50, TABLES, RULES, l50, catalog=[shield(2, "wiki")])
    before = copy.deepcopy(made)
    got = assemble(made, "HUM", "tank", "own", evidence="wiki")
    got["setups"].append("x")
    assemble(made, "HUM", "tank", "own", evidence="strict")["setups"].clear()
    assert made == before


def test_the_bundle_of_a_small_catalog_is_plain_json_and_the_same_every_time(l50):
    listed = [levelled(1, "strict"), shield(2, "wiki")]
    first, second = (bundle(PBM, 50, TABLES, RULES, l50, catalog=listed) for _ in range(2))
    text = json.dumps(first, allow_nan=False)
    assert json.loads(text) == first and json.dumps(second) == text
    document = {"version": "2030-01-02", "items": listed}
    assert bundle(PBM, 50, TABLES, RULES, l50, catalog=document) == first  # the document works as well as its items


def test_without_a_catalog_the_bundle_reads_the_one_the_command_reads_by_default(l50):
    found = grid.find_catalog()  # what the command reads when it is not given --catalog
    assert found is not None
    document = loads_strict(found.read_text(encoding="utf-8"), found.name)
    assert bundle(PBM, 50, TABLES, RULES, l50) == bundle(PBM, 50, TABLES, RULES, l50, catalog=document)


def test_the_catalog_that_is_found_on_disk_is_the_default(monkeypatch, tmp_path, l50):
    listed = [levelled(1, "strict"), shield(2, "wiki")]
    path = write_catalog(tmp_path, listed)
    monkeypatch.setattr(grid, "find_catalog", lambda: path)
    found = bundle(PBM, 50, TABLES, RULES, l50)
    assert found["roles"]["tank"]["setups_by_evidence"] == {"strict": WITHOUT_SHIELD, "wiki": WITH_SHIELD}
    assert found == bundle(PBM, 50, TABLES, RULES, l50, catalog=listed)
    write_catalog(tmp_path, [levelled(1, "strict"), shield(2, "strict"), shield(3, "wiki")])  # changed: read again
    assert bundle(PBM, 50, TABLES, RULES, l50)["roles"]["tank"]["setups_by_evidence"]["strict"] == WITH_SHIELD


def test_with_no_catalog_to_read_a_shield_is_assumed_at_both_levels(monkeypatch, l50):
    monkeypatch.setattr(grid, "find_catalog", lambda: None)
    made = bundle(PBM, 50, TABLES, RULES, l50)
    assert made["roles"]["tank"]["setups"] == WITH_SHIELD
    for row in made["roles"].values():
        assert row["setups_by_evidence"] == {"strict": row["setups"], "wiki": row["setups"]}


def test_a_catalog_that_is_not_the_builders_is_refused(l50):
    for bad in ([{"name": "no key and no evidence"}], ["Item"]):
        with pytest.raises(ValueError, match="evidence"):
            bundle(PBM, 50, TABLES, RULES, l50, catalog=bad)


def test_a_shield_that_only_some_races_may_wear_does_not_make_the_shield_setup_of_every_race(l50):
    only_elves = shield(2, "wiki", races=["ELF"])
    for listed in ([only_elves], [only_elves, shield(3, "strict", races=["ELF", "HUM"])]):
        with pytest.raises(ValueError, match="depend on the race"):
            bundle(PBM, 50, TABLES, RULES, l50, catalog=listed)  # the bundle holds one list for each role and level
    made = bundle(PBM, 50, TABLES, RULES, l50, catalog=[only_elves, shield(3, "wiki")])  # a shield for all settles it
    assert made["roles"]["tank"]["setups_by_evidence"] == {"strict": WITHOUT_SHIELD, "wiki": WITH_SHIELD}


def test_a_bundle_whose_setups_do_not_reassemble_for_an_evidence_level_is_never_returned(monkeypatch, l50):
    real = browser.assemble

    def broken(data, race, role, buffs, **options):
        got = real(data, race, role, buffs, **options)
        if options.get("evidence") == "wiki":
            got["setups"] = [*got["setups"], "stick"]
        return got

    monkeypatch.setattr(browser, "assemble", broken)
    with pytest.raises(RuntimeError, match="reassemble"):
        bundle(PBM, 50, TABLES, RULES, l50, catalog=[shield(2, "wiki")])


def test_the_command_gives_the_bundle_the_catalog_it_reads(tmp_path):
    # a strict shield: the real catalog has none, so a bundle made from another catalog would show it
    path = write_catalog(tmp_path, [shield(2, "strict")], "small.json")
    assert browser.main(["--out", str(tmp_path / "o"), "--trio", "pal-mnk-ber", "--catalog", str(path)]) == 0
    written = json.loads((tmp_path / "o" / "bundles" / "pal-mnk-ber-l50.json").read_text(encoding="utf-8"))
    assert written["roles"]["tank"]["setups_by_evidence"] == {"strict": WITH_SHIELD, "wiki": WITH_SHIELD}
    assert assemble(written, "HUM", "tank", "own", evidence="strict")["setups"] == WITH_SHIELD
    empty = write_catalog(tmp_path, [levelled(1, "wiki")], "bare.json")  # and one with no shield: the real one has many
    assert browser.main(["--out", str(tmp_path / "p"), "--trio", "pal-mnk-ber", "--catalog", str(empty)]) == 0
    bare = json.loads((tmp_path / "p" / "bundles" / "pal-mnk-ber-l50.json").read_text(encoding="utf-8"))
    assert bare["roles"]["tank"]["setups_by_evidence"] == {"strict": WITHOUT_SHIELD, "wiki": WITHOUT_SHIELD}


# ---- the command -----------------------------------------------------------------------------------------------------


def test_the_command_writes_a_bundle_for_each_trio_and_one_item_table_and_reports_sizes(tmp_path, capsys):
    out = tmp_path / "browser"
    code = browser.main(["--out", str(out), "--trio", "pal-mnk-ber", "--trio", "WIZ-MAG-ENC"])
    assert code == 0
    first = json.loads((out / "bundles" / "pal-mnk-ber-l50.json").read_text(encoding="utf-8"))
    assert first["trio"] == ["PAL", "MNK", "BER"] and first["data_release"].startswith("data-")
    assert (out / "bundles" / "wiz-mag-enc-l50.json").is_file()
    table = json.loads((out / "items.json").read_text(encoding="utf-8"))
    assert table["count"] == len(table["items"]) > 6000
    report = capsys.readouterr().out
    for name in ("bundles/pal-mnk-ber-l50.json", "bundles/wiz-mag-enc-l50.json", "items.json"):
        row = [line for line in report.splitlines() if name in line]
        assert row and re.search(r"\d+ bytes", row[0]) and re.search(r"\d+ gzip", row[0])
    listed = browser.shared_match_names(table)
    expected = f"match names shared by more than one item: {len(listed)} ({sum(map(len, listed.values()))} items)"
    assert [line for line in report.splitlines() if line.startswith("match names shared")] == [expected]


def test_the_command_writes_the_same_bytes_twice(tmp_path):
    for name in ("a", "b"):
        assert browser.main(["--out", str(tmp_path / name), "--trio", "pal-mnk-ber"]) == 0
    for relative in ("bundles/pal-mnk-ber-l50.json", "items.json"):
        assert (tmp_path / "a" / relative).read_bytes() == (tmp_path / "b" / relative).read_bytes()
        assert (tmp_path / "a" / relative).read_bytes().endswith(b"\n")


def test_the_command_reassembles_what_it_wrote(tmp_path, l50):
    browser.main(["--out", str(tmp_path), "--trio", "shd-clr-shm"])  # the page and the file take the class order
    written = json.loads((tmp_path / "bundles" / "clr-shd-shm-l50.json").read_text(encoding="utf-8"))
    trio = grid.parse_trio("shd-clr-shm")
    expected = reference_dict(trio, 50, "HUM", "tank", buffsets_for(trio, 50, l50)["raid"])
    assert assemble(written, "HUM", "tank", "raid") == expected


def test_the_command_refuses_a_bad_trio_a_missing_catalog_and_a_level_without_client_data(tmp_path, capsys):
    out = str(tmp_path / "x")
    assert browser.main(["--out", out, "--trio", "pal-mnk"]) == 2
    assert browser.main(["--out", out, "--trio", "pal-mnk-ber", "--catalog", str(tmp_path / "none.json")]) == 2
    assert browser.main(["--out", out, "--trio", "pal-mnk-ber", "--level", "77"]) == 2
    assert not (tmp_path / "x").exists() or not list((tmp_path / "x").rglob("*.json"))
    assert capsys.readouterr().err.count("trioforge.export.browser") >= 3


def test_the_item_table_of_a_small_catalog_goes_through_the_command(tmp_path):
    catalog = {"version": "2030-01-02", "items": [cat_item(3, "Third"), cat_item(1, "First (Dup)")]}
    path = tmp_path / "small.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    assert browser.main(["--out", str(tmp_path / "o"), "--trio", "pal-mnk-ber", "--catalog", str(path)]) == 0
    table = json.loads((tmp_path / "o" / "items.json").read_text(encoding="utf-8"))
    assert table["data_release"] == "data-2030-01-02" and [r["id"] for r in table["items"]] == [1, 3]
    first = json.loads((tmp_path / "o" / "bundles" / "pal-mnk-ber-l50.json").read_text(encoding="utf-8"))
    assert first["data_release"] == "data-2030-01-02"  # the bundle carries the release of the catalog it is used with


def test_rat_writes_reduced_ratios_and_unrat_reads_only_those():
    assert browser.rat(255) == "255/1" and browser.rat(0.2222) == "1111/5000" and browser.rat(Fraction(8, 6)) == "4/3"
    assert browser.rat(-73) == "-73/1" and browser.rat(1.5) == "3/2" and browser.rat(0) == "0/1"
    for text in ("255/1", "1111/5000", "-73/1", "0/1", "3/2"):
        assert browser.rat(browser.unrat(text)) == text
    for bad in ("2/4", "4/0", "1.5", "3", " 3/1", "03/1", "-0/1", "3/-1", "1/2/3", "", None, 3, 1.5):
        with pytest.raises(ValueError, match="rational"):
            browser.unrat(bad)
    with pytest.raises(TypeError):
        browser.rat(True)


def test_float_of_a_fraction_overflows_at_the_tie_below_two_to_the_1024th_for_either_sign():
    """The browser's ``Rational.toNumber`` throws where ``float(Fraction)`` raises OverflowError, and gives the largest double up to
    the same point: tests-js/engine-rational.test.mjs holds it to the boundary that is found here by asking ``float`` itself."""

    def overflows(value):
        try:
            float(value)
        except OverflowError:
            return True
        return False

    low, high = 2**1023, 2**1025  # a whole number that has a double, and one that has none
    assert not overflows(Fraction(low)) and overflows(Fraction(high))
    while high - low > 1:
        middle = (low + high) // 2
        low, high = (low, middle) if overflows(Fraction(middle)) else (middle, high)
    assert high == 2**1024 - 2**970  # the tie between the largest double and 2**1024 goes to the even one, 2**1024
    assert low == high - 1 and float(Fraction(low)) == sys.float_info.max
    for sign in (1, -1):
        assert float(sign * Fraction(low)) == sign * sys.float_info.max and overflows(sign * Fraction(high))
        for denominator in (2, 3, 7, 10**6, 10**400 + 7):  # and for ratios, at the tie and a hair on either side of it
            assert float(sign * Fraction(high * denominator - 1, denominator)) == sign * sys.float_info.max
            assert overflows(sign * Fraction(high * denominator + 1, denominator))
        assert overflows(sign * Fraction(2**1030)) and overflows(sign * Fraction(10**400))
    assert float(Fraction(3 * 10**400 + 1, 10**400)) == 3.0 and overflows(Fraction(10**709 + 1, 10**400))


def test_a_bundle_that_does_not_reassemble_is_never_returned(monkeypatch, l50):
    real = browser.assemble

    def broken(data, race, role, buffs, **options):
        got = real(data, race, role, buffs, **options)
        got["weights"] = {**got["weights"], "HP": got["weights"]["HP"] + 1}
        return got

    monkeypatch.setattr(browser, "assemble", broken)
    with pytest.raises(RuntimeError, match="reassemble"):
        bundle(("PAL", "MNK", "BER"), 50, TABLES, RULES, l50)


def test_the_numbers_are_exact_whatever_the_python_float_repr(pmb):
    # a float that is not an exact decimal must still be read as the decimal text it prints as (4.8 is 24/5)
    assert decode(pmb["constants"]["str_to_atk"]) == Fraction(666667, 1000000)
    assert decode(pmb["constants"]["agi_to_ac"]) == Fraction(1111, 5000)
    assert math.isclose(float(decode(pmb["constants"]["sheet"]["item_mult"])), 4 / 3)


# ---- the seen flags of a precompute run, merged into the table and the bundle the way the run merges them --------------------
# The run solves with the catalog and the maintainer's private list of keys seen in game: a seen item is strict unless a patch or
# a research removal hides it (grid.select_items). The engine files of that run must carry those levels, not the catalog's own.

REMOVED = {"code": "removed-by-patch", "seal": "client", "text": "Removed by a patch."}


def seen_catalog():
    return [
        levelled(1, "wiki"),
        levelled(2, "wiki"),
        levelled(3, "hidden"),
        levelled(4, "disputed"),
        levelled(5, "strict"),
        cat_item(6, "Item 6", evidence={"level": "wiki", "reasons": [REMOVED]}),
        shield(7, "wiki"),
    ]


def levels_of(table):
    return {key_of(record): record["evidence"]["level"] for record in table["items"]}


def test_a_seen_item_is_strict_in_the_table_unless_a_patch_removed_it_and_the_rest_keep_their_levels():
    seen = {"w1", "w3", "w4", "w6", "w5", "w99404"}  # w99404 is not in the catalog: it is ignored
    table = items(seen_catalog(), RULES, seen=seen)
    assert levels_of(table) == {"w1": "strict", "w2": "wiki", "w3": "strict", "w4": "strict", "w5": "strict", "w6": "wiki", "w7": "wiki"}
    assert table["count"] == len(table["items"]) == 7
    # the level is the one the run's pools use for the items of the trio
    selection = grid.select_items(seen_catalog(), PBM, seen)
    assert selection.levels and all(levels_of(table)[key] == level for key, level in selection.levels.items())


def test_an_item_the_seen_flags_made_strict_is_no_longer_owned_only_and_its_reasons_are_the_catalogs():
    plain, merged = items(seen_catalog(), RULES), items(seen_catalog(), RULES, seen={"w3"})
    before = next(r for r in plain["items"] if key_of(r) == "w3")
    after = next(r for r in merged["items"] if key_of(r) == "w3")
    assert before["owned_only"] is True and before["evidence"] == {"level": "hidden"}
    assert "owned_only" not in after and after["evidence"] == {"level": "strict"}
    # every other record is the record it was
    assert [r for r in merged["items"] if key_of(r) != "w3"] == [r for r in plain["items"] if key_of(r) != "w3"]


def test_without_seen_flags_the_table_is_what_it_was_and_a_private_flag_is_never_written_as_a_reason():
    assert items(seen_catalog(), RULES, seen=()) == items(seen_catalog(), RULES) == items(seen_catalog(), RULES, seen=frozenset())
    text = json.dumps(items(seen_catalog(), RULES, seen={"w1", "w2", "w3"}))
    assert "seen-in-game" not in text and "seen" not in text


def test_the_seen_flags_are_a_set_of_keys_and_a_text_alone_is_refused():
    with pytest.raises(ValueError, match="seen"):
        items(seen_catalog(), RULES, seen="w1")
    with pytest.raises(ValueError, match="seen"):
        bundle(PBM, 50, TABLES, RULES, spells_file(50), catalog=seen_catalog(), seen="w7")


def test_a_seen_shield_makes_the_shield_setup_a_setup_of_the_strict_level_in_the_bundle(l50):
    plain = bundle(PBM, 50, TABLES, RULES, l50, catalog=seen_catalog())
    merged = bundle(PBM, 50, TABLES, RULES, l50, catalog=seen_catalog(), seen={"w7"})
    assert plain["roles"]["tank"]["setups_by_evidence"] == {"strict": WITHOUT_SHIELD, "wiki": WITH_SHIELD}
    assert merged["roles"]["tank"]["setups_by_evidence"] == {"strict": WITH_SHIELD, "wiki": WITH_SHIELD}
    assert assemble(merged, "HUM", "tank", "own", evidence="strict")["setups"] == WITH_SHIELD
    # the profile the precompute makes for the level is the one the bundle reassembles
    selection = grid.select_items(seen_catalog(), PBM, {"w7"})
    pools = {label: [at_tier(item, 0, RULES) for item in grid.pool_dicts(selection, label)] for label in grid.EVIDENCE}
    buffsets = buffsets_for(PBM, 50, l50)
    for label in grid.EVIDENCE:
        made = make_profile("HUM", PBM, 50, "tank", buffsets["own"], None, TABLES, evidence=label, items=pools[label])
        assert assemble(merged, "HUM", "tank", "own", evidence=label) == made.to_dict()


def test_a_seen_flag_that_removes_nothing_leaves_the_bundle_alone_when_no_pool_changes(l50):
    assert bundle(PBM, 50, TABLES, RULES, l50, catalog=seen_catalog(), seen={"w99404"}) == bundle(PBM, 50, TABLES, RULES, l50, catalog=seen_catalog())


def test_the_texts_of_the_two_files_are_the_ones_the_command_writes(tmp_path, l50):
    listed = [levelled(1, "strict"), shield(2, "wiki")]
    path = write_catalog(tmp_path, listed, "small.json")
    assert browser.main(["--out", str(tmp_path / "o"), "--trio", "pal-mnk-ber", "--catalog", str(path)]) == 0
    document = {"version": "2030-01-02", "items": listed}
    made = bundle(PBM, 50, TABLES, RULES, l50, data_release="data-2030-01-02", catalog=document)
    assert browser.render_bundle(made) == (tmp_path / "o" / "bundles" / "pal-mnk-ber-l50.json").read_text(encoding="utf-8")
    assert browser.render_items(items(document, RULES)) == (tmp_path / "o" / "items.json").read_text(encoding="utf-8")


def test_the_bundle_names_its_top_level_fields_once_for_whoever_reads_it_back(pmb):
    assert list(pmb) == list(browser.BUNDLE_FIELDS) == list(REQUIRED)
    assert browser.ITEM_TABLE_FIELDS == ("version", "data_release", "rules_version", "count", "defaults", "items")
    assert list(items([cat_item(1, "One")], RULES)) == list(browser.ITEM_TABLE_FIELDS)


# ---- the fingerprint of the inputs of a run ------------------------------------------------------------------------------
# The precompute puts one in the bundle of each trio and one in the item table of the folder, so that the build can tell files that were made from other
# catalogs or from other flags merged into the levels: the SHA-256 of the catalog (the hash of its file) and of the evidence level of every item of the table.
# It is a function of what the published table says and of nothing that is not in it: no flag, and no flag that changes no level.

CATALOG_SHA = "ab" * 32


def test_the_fingerprint_is_the_sha256_of_the_catalog_and_of_the_key_and_level_of_every_item_of_the_table():
    table = items(seen_catalog(), RULES, seen={"w1", "w3"})
    listed = [[key_of(record), record["evidence"]["level"]] for record in table["items"]]
    expected = hashlib.sha256(json.dumps({"catalog": CATALOG_SHA, "levels": listed}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    fingerprint = browser.inputs_fingerprint(CATALOG_SHA, table)
    assert fingerprint == expected and re.fullmatch(r"[0-9a-f]{64}", fingerprint)


def test_the_fingerprint_changes_with_the_catalog_and_with_a_level_and_with_nothing_else():
    plain = items(seen_catalog(), RULES)
    base = browser.inputs_fingerprint(CATALOG_SHA, plain)
    assert browser.inputs_fingerprint(CATALOG_SHA, items(seen_catalog(), RULES)) == base  # the same inputs
    assert browser.inputs_fingerprint("cd" * 32, plain) != base  # another catalog
    assert browser.inputs_fingerprint(CATALOG_SHA, items(seen_catalog(), RULES, seen={"w1"})) != base  # a flag that changes a level
    # flags that change no level are not in it: w99404 is in no catalog, w5 is strict already, w6 is removed by a patch and stays wiki
    assert browser.inputs_fingerprint(CATALOG_SHA, items(seen_catalog(), RULES, seen={"w99404", "w5", "w6"})) == base
    assert browser.inputs_fingerprint(CATALOG_SHA, items(seen_catalog(), RULES, seen={"w1", "w99404"})) == browser.inputs_fingerprint(
        CATALOG_SHA, items(seen_catalog(), RULES, seen={"w1"})
    )


def test_the_fingerprint_does_not_carry_the_flags_that_made_the_levels():
    """A digest of the list of flags could be tried against guesses about flags that change no level; this one is made of the published table alone."""
    table = items(seen_catalog(), RULES, seen={"w1", "w3"})
    flags_digest = hashlib.sha256("\n".join(sorted({"w1", "w3"})).encode()).hexdigest()
    assert flags_digest != browser.inputs_fingerprint(CATALOG_SHA, table)
    with pytest.raises(TypeError):
        browser.inputs_fingerprint(CATALOG_SHA, table, {"w1", "w3"})  # it takes no flags


@pytest.mark.parametrize("sha", ["", "AB" * 32, "ab" * 31, "ab" * 33, "gg" * 32, None, 5, b"ab" * 32])
def test_the_fingerprint_refuses_a_catalog_digest_that_is_not_a_sha256(sha):
    with pytest.raises(ValueError, match="SHA-256"):
        browser.inputs_fingerprint(sha, items(seen_catalog(), RULES))


def test_with_inputs_puts_the_fingerprint_after_the_rules_version_in_a_bundle_and_in_a_table(l50):
    fingerprint = browser.inputs_fingerprint(CATALOG_SHA, items(seen_catalog(), RULES))
    table = browser.with_inputs(items(seen_catalog(), RULES), fingerprint)
    assert list(table) == ["version", "data_release", "rules_version", "inputs", "count", "defaults", "items"] and table["inputs"] == fingerprint
    made = bundle(PBM, 50, TABLES, RULES, l50, catalog=seen_catalog())
    stamped = browser.with_inputs(made, fingerprint)
    assert list(stamped) == ["version", "data_release", "rules_version", "inputs", *list(browser.BUNDLE_FIELDS)[3:]] and stamped["inputs"] == fingerprint
    assert "inputs" not in made  # the document that was given is not changed
    assert browser.INPUTS_FIELD == "inputs" and f'"inputs": "{fingerprint}"' in browser.render_items(table)
    # a stamped bundle is still a bundle: it reassembles to the profiles it did
    assert assemble(stamped, "HUM", "tank", "own", evidence="strict") == assemble(made, "HUM", "tank", "own", evidence="strict")


@pytest.mark.parametrize("bad", ["", "AB" * 32, "ab" * 31, "gg" * 32, None, 5])
def test_with_inputs_refuses_what_is_not_a_fingerprint_and_a_document_that_has_one(bad):
    with pytest.raises(ValueError, match="fingerprint"):
        browser.with_inputs(items(seen_catalog(), RULES), bad)
    stamped = browser.with_inputs(items(seen_catalog(), RULES), "ab" * 32)
    with pytest.raises(ValueError, match="already"):
        browser.with_inputs(stamped, "cd" * 32)
