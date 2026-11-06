"""Tests for the versioned rules file: rules/rules.json, its schema and the loader.

Rules built in memory use the invented id ``x.y``.
"""

import json
import math
import re
import types
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import trioforge.rules as rules_module
from trioforge.rules import Rules, RulesError, load

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = REPO_ROOT / "rules" / "rules.json"
SCHEMA_PATH = REPO_ROOT / "rules" / "rules.schema.json"

# The five confidence seals. Written out here on purpose, so these tests do not
# trust the schema they are checking.
SEALS = {"client", "developer", "measured", "player", "model"}

# What a source may be. Written out here, like SEALS, so these tests do not
# trust the schema they are checking.
SOURCE_KINDS = {"url", "client-file", "public-text", "private-measured", "private-player"}
PRIVATE_LABEL = "maintainer's private observation"  # the only ref a private-* source may carry
CLIENT_FILES = {
    "Resources/ZoneNames.txt",
    "Resources/basedata.txt",
    "Resources/ACMitigation.txt",
    "Resources/skillcaps.txt",
    "spells_us.txt",
    "dbstr_us.txt",
    "eqstr_us.txt",
}

REQUIRED_FIELDS = ("id", "title", "value", "unit", "seal", "source", "date", "status")

# The ids of the rules file, in file order (monk.weight_curve replaced an earlier
# monk.weight_threshold). A dropped, renamed or added rule fails the test; changing this
# list is a deliberate act.
EXPECTED_IDS = (
    "level.current",
    "naked.cap",
    "naked.rule",
    "hp.pools_counted",
    "hp.sta_curve",
    "hp.natural_durability_pct",
    "mana.pools_counted",
    "mana.base_l50",
    "mana.per_stat_l50",
    "mana.wis_bands",
    "mana.stat_by_class",
    "end.formula",
    "ac.sheet.item_mult",
    "ac.sheet.defense_div",
    "ac.sheet.spell_ac_div",
    "ac.sheet.agi_div",
    "ac.softcap.past_cap_rate",
    "ac.softcap.combat_stability_pct",
    "ac.softcap.physical_enhancement_pct",
    "ac.softcap.pe_for_caster_only_trios",
    "ac.shield.offhand_raises_cap",
    "stats.knee",
    "stats.hard_cap",
    "stats.str_to_atk",
    "stats.agi_to_ac",
    "stats.dex_post255_slope",
    "haste.cap_pct",
    "haste.cap_pct_with_monk",
    "haste.worn_per_tier",
    "haste.unbound_alacrity",
    "regen.gear_caps",
    "regen.per_tier",
    "regen.value_minutes",
    "resist.cap",
    "tier.stat_rule",
    "tier.weight_floor",
    "tier.weight_pct",
    "tier.weapon_damage_pct",
    "tier.accuracy_pct",
    "tier.socket_open",
    "tier.arrival",
    "tier.max_fresh_drop",
    "tier.exp_needed",
    "tier.negatives_scale",
    "monk.weight_curve",
    "monk.bonus_placement",
    "packrat.pct_per_rank",
    "race.iksar_ac_bonus",
    "race.iksar_ac_placement",
    "buffs.min_duration_minutes",
    "buffs.max_slots",
    "roles.templates",
    "roles.balanced",
    "weapons.damage_weight",
    "weapons.dual_wield_factor",
    "effects.focus_value",
    "effects.spell_weight",
    "effects.cast_categories",
    "effects.cast_mass_full",
    "effects.late_level",
    "effects.click_relevance",
    "effects.dispel_relevance",
    "effects.gap_categories",
    "effects.own_compare",
    "effects.instant_categories",
    "effects.instant_bonus",
    "effects.proc_value",
    "effects.score_shape",
    "effects.haste_buff",
    "effects.near_best",
    "effects.access_cost",
    "effects.raid_zones",
    "effects.one_off_spas",
    "effects.restricted_targets",
    "effects.unverified_names",
    "effects.rows_kept",
)

# The rules that carry an `alternatives` list.
RULES_WITH_ALTERNATIVES = {"monk.weight_curve", "monk.bonus_placement", "tier.weapon_damage_pct"}

# The sources of every rule, as (kind, ref) pairs in list order, written out. Dropping,
# adding or changing a source fails test_rule_sources_match_the_expected_sources.
EQEMU = ("url", "https://github.com/EQEmu/Server")
TOOLS_ATTRIBUTES = ("url", "https://eqltools.com/attributes")
TOOLS_COMBAT = ("url", "https://eqltools.com/combat")
WIKI_UPGRADES = ("url", "https://eqlwiki.com/Item_Upgrade_System")
WIKI_UPGRADES_INDEX = ("url", "https://eqlwiki.com/index.php/Item_Upgrade_System")
CLIENT_READS = ("url", "https://xm2514-svg.github.io/sites/item-upgrades/")
BASEDATA = ("client-file", "Resources/basedata.txt")
PRIVATE_MEASURED = ("private-measured", PRIVATE_LABEL)
PRIVATE_PLAYER = ("private-player", PRIVATE_LABEL)
JUDGMENT = ("public-text", "TrioForge judgment")

EXPECTED_SOURCES = {
    "level.current": [("public-text", "developer announcements (level cap until Rulers of Kunark)")],
    "naked.cap": [PRIVATE_MEASURED],
    "naked.rule": [TOOLS_ATTRIBUTES, PRIVATE_MEASURED],
    "hp.pools_counted": [BASEDATA, PRIVATE_MEASURED],
    "hp.sta_curve": [EQEMU, PRIVATE_PLAYER],
    "hp.natural_durability_pct": [("client-file", "dbstr_us.txt"), ("public-text", "eqlwiki AA data, revision 151303, as extracted by eqlbuilds.com")],
    "mana.pools_counted": [PRIVATE_MEASURED],
    "mana.base_l50": [BASEDATA],
    "mana.per_stat_l50": [BASEDATA],
    "mana.wis_bands": [EQEMU, PRIVATE_MEASURED],  # settled by an in-game reading
    "mana.stat_by_class": [("client-file", "eqstr_us.txt")],
    "end.formula": [EQEMU, PRIVATE_MEASURED],
    "ac.sheet.item_mult": [EQEMU, PRIVATE_MEASURED],
    "ac.sheet.defense_div": [EQEMU, PRIVATE_MEASURED],
    "ac.sheet.spell_ac_div": [EQEMU, PRIVATE_MEASURED],
    "ac.sheet.agi_div": [EQEMU],
    "ac.softcap.past_cap_rate": [("client-file", "Resources/ACMitigation.txt")],
    "ac.softcap.combat_stability_pct": [EQEMU, PRIVATE_PLAYER],
    "ac.softcap.physical_enhancement_pct": [EQEMU, PRIVATE_PLAYER],
    "ac.softcap.pe_for_caster_only_trios": [("url", "https://eqlwiki.com/"), ("public-text", "in-game AA list")],
    "ac.shield.offhand_raises_cap": [TOOLS_COMBAT, PRIVATE_MEASURED],
    "stats.knee": [TOOLS_ATTRIBUTES, PRIVATE_PLAYER],
    "stats.hard_cap": [TOOLS_ATTRIBUTES, PRIVATE_PLAYER],
    "stats.str_to_atk": [EQEMU],
    "stats.agi_to_ac": [EQEMU],
    "stats.dex_post255_slope": [PRIVATE_PLAYER],
    "haste.cap_pct": [PRIVATE_PLAYER],
    "haste.cap_pct_with_monk": [("public-text", "patch notes, Unbound Alacrity"), PRIVATE_PLAYER],
    "haste.worn_per_tier": [PRIVATE_PLAYER],
    "haste.unbound_alacrity": [
        ("public-text", 'patch notes 2026-07-28, Unbound Alacrity ("increase in your current and maximum haste value")'),
        ("url", "https://eqlwiki.com/Haste_Guide"),
    ],
    "regen.gear_caps": [PRIVATE_PLAYER],
    "regen.per_tier": [WIKI_UPGRADES, PRIVATE_PLAYER],
    "regen.value_minutes": [JUDGMENT],
    "resist.cap": [JUDGMENT],
    "tier.stat_rule": [WIKI_UPGRADES],
    "tier.weight_floor": [WIKI_UPGRADES],
    "tier.weight_pct": [CLIENT_READS, WIKI_UPGRADES_INDEX],
    "tier.weapon_damage_pct": [CLIENT_READS, WIKI_UPGRADES_INDEX],
    "tier.accuracy_pct": [("public-text", "patch notes 2026-09-22")],
    "tier.socket_open": [WIKI_UPGRADES, ("public-text", "developer demo")],
    "tier.arrival": [("public-text", "developer hotfix notes 2026-07-29 and developer stream 2026-06-10")],
    "tier.max_fresh_drop": [("public-text", "developer hotfix notes 2026-07-29"), PRIVATE_MEASURED],
    "tier.exp_needed": [("url", "https://eqlwiki.com/Mote_Guide")],
    "tier.negatives_scale": [PRIVATE_MEASURED],
    "monk.weight_curve": [TOOLS_COMBAT],
    "monk.bonus_placement": [TOOLS_COMBAT],
    "packrat.pct_per_rank": [("client-file", "dbstr_us.txt")],
    "race.iksar_ac_bonus": [TOOLS_COMBAT],
    "race.iksar_ac_placement": [TOOLS_COMBAT],
    "buffs.min_duration_minutes": [JUDGMENT],
    "buffs.max_slots": [JUDGMENT],
    "roles.templates": [JUDGMENT],
    "roles.balanced": [JUDGMENT],
    "weapons.damage_weight": [JUDGMENT],
    "weapons.dual_wield_factor": [("url", "https://eqlwiki.com/Skill_Dual_Wield")],
    "effects.focus_value": [JUDGMENT],
    "effects.spell_weight": [JUDGMENT],
    "effects.cast_categories": [JUDGMENT],
    "effects.cast_mass_full": [JUDGMENT],
    "effects.late_level": [JUDGMENT],
    "effects.click_relevance": [JUDGMENT],
    "effects.dispel_relevance": [JUDGMENT],
    "effects.gap_categories": [JUDGMENT],
    "effects.own_compare": [JUDGMENT],
    "effects.instant_categories": [JUDGMENT],
    "effects.instant_bonus": [JUDGMENT],
    "effects.proc_value": [JUDGMENT],
    "effects.score_shape": [JUDGMENT],
    "effects.haste_buff": [JUDGMENT],
    "effects.near_best": [JUDGMENT],
    "effects.access_cost": [JUDGMENT],
    "effects.raid_zones": [JUDGMENT],
    "effects.one_off_spas": [JUDGMENT],
    "effects.restricted_targets": [JUDGMENT],
    "effects.unverified_names": [JUDGMENT],
    "effects.rows_kept": [JUDGMENT],
}

# The sources of each alternative, per rule, in list order. monk.bonus_placement's
# alternative cites EQEmu's ACSum, the same address the other ACSum rules cite.
EXPECTED_ALTERNATIVE_SOURCES = {
    "tier.weapon_damage_pct": [[WIKI_UPGRADES]],
    "monk.weight_curve": [[TOOLS_COMBAT]],
    "monk.bonus_placement": [[EQEMU]],
}


def source(kind="public-text", ref="unit test"):
    """One source object."""
    return {"kind": kind, "ref": ref}


def private(kind="private-measured"):
    """A private source, with the one ref it may carry."""
    return source(kind, PRIVATE_LABEL)


def make_rule(**overrides):
    """A minimal valid rule; keyword arguments override or add fields."""
    rule = {
        "id": "x.y",
        "title": "Test rule",
        "value": 17,
        "unit": "points",
        "seal": "model",
        "source": [source()],
        "date": "2026-10-13",
        "status": "active",
    }
    rule.update(overrides)
    return rule


def forbidden_words_in(text: str) -> list[str]:
    """Words that would mean a source cites a client binary, an address in it or a disassembly.

    All are matched without regard to case except RVA, whose lowercase form sits inside
    ordinary words (the private label itself contains it, in "observation").
    """
    lowered = text.lower()
    found = [word for word in ("eqgame", ".exe", "offset", "0x") if word in lowered]
    if "RVA" in text:
        found.append("RVA")
    return found


def source_defects(sources) -> list[str]:
    """What is wrong with a list of source objects, judged here and not by the schema."""
    if not isinstance(sources, list) or not sources:
        return ["not a non-empty list"]
    defects = []
    for entry in sources:
        if not isinstance(entry, dict) or set(entry) != {"kind", "ref"}:
            defects.append(f"not a {{kind, ref}} object: {entry!r}")
            continue
        kind, ref = entry["kind"], entry["ref"]
        if kind not in SOURCE_KINDS:
            defects.append(f"unknown kind {kind!r}")
        elif not isinstance(ref, str) or not ref.strip():
            defects.append(f"{kind}: blank or non-string ref {ref!r}")
        elif kind == "url" and not (
            ref.startswith("https://") and len(ref) > len("https://") and not re.search(r"\s", ref)
        ):
            defects.append(f"url ref is not an https:// address: {ref!r}")
        elif kind == "client-file" and ref not in CLIENT_FILES:
            defects.append(f"client-file ref is not on the list: {ref!r}")
        elif kind.startswith("private-") and ref != PRIVATE_LABEL:
            defects.append(f"{kind} ref is not the fixed label: {ref!r}")
    return defects


def all_sources(raw):
    """Every (where, sources) pair of the real file: each rule's own and its alternatives'."""
    for rule in raw["rules"]:
        yield rule["id"], rule["source"]
        for number, alternative in enumerate(rule.get("alternatives", [])):
            yield f"{rule['id']} alternatives[{number}]", alternative["source"]


def has_private_source(rule) -> bool:
    return any(
        entry["kind"].startswith("private-")
        for _, sources in all_sources({"rules": [rule]})
        for entry in sources
    )


def make_file(*rules, version="2026-10-13"):
    return {"version": version, "rules": list(rules)}


def rejection(data) -> str:
    """The message of the RulesError raised for ``data``; fails the test if it is accepted."""
    with pytest.raises(RulesError) as info:
        Rules(data)
    return str(info.value)


def write(tmp_path, text, name="rules.json"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def raw():
    """The real rules file as plain JSON data, read without the loader."""
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


# ---- the real file ------------------------------------------------------------------


def test_real_rules_file_loads_and_validates():
    rules = load(RULES_PATH)
    assert isinstance(rules, Rules)
    assert rules.version == "2026-10-13"


def test_schema_is_draft_2020_12_and_accepts_the_real_file_on_its_own(raw):
    # The schema must stand alone (editors, other languages), not only through load().
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    assert list(validator.iter_errors(raw)) == []


@pytest.mark.parametrize("bad", ["nope", "2026-1-5", "20261013", "2026-10-13T00:00:00", " 2026-10-13"])
def test_schema_alone_rejects_a_misshapen_date_even_when_format_is_not_asserted(bad):
    # JSON Schema treats 'format' as an annotation unless the validator asserts it, so the
    # schema carries a 'pattern' for the shape; only the loader's format checker can also
    # reject impossible dates such as 2026-13-01.
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(make_file(make_rule(date=bad)))) != []
    assert list(validator.iter_errors(make_file(make_rule(), version=bad))) != []


def test_load_without_arguments_finds_the_repo_file_from_any_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load().get("level.current") == load(RULES_PATH).get("level.current")


# ---- the lookup API -----------------------------------------------------------------


def test_levels_override_value_only_at_their_level():
    rules = Rules(make_file(make_rule(value=17, levels={"55": 20})))
    assert rules.get("x.y", 55) == 20
    assert rules.get("x.y", 50) == 17
    assert rules.get("x.y") == 17  # the default level is 50
    assert rules.get("x.y", 60) == 17  # a level without an override falls back to value


def test_a_level_override_for_the_default_level_applies_to_get_without_a_level():
    rules = Rules(make_file(make_rule(value=17, levels={"50": 18})))
    assert rules.get("x.y") == 18


def test_unknown_id_raises_keyerror():
    rules = Rules(make_file(make_rule()))
    with pytest.raises(KeyError):
        rules.get("no.such.rule")
    with pytest.raises(KeyError):
        rules.seal("no.such.rule")


def test_superseded_rules_load_but_are_not_referenced():
    rules = Rules(make_file(make_rule(), make_rule(id="old.rule", status="superseded")))
    assert rules.get("x.y") == 17
    with pytest.raises(KeyError):
        rules.get("old.rule")
    with pytest.raises(KeyError):
        rules.seal("old.rule")


def test_seal_returns_the_seal_of_the_rule():
    rules = Rules(make_file(make_rule(seal="measured"), make_rule(id="a.b", seal="client")))
    assert rules.seal("x.y") == "measured"
    assert rules.seal("a.b") == "client"


def test_get_returns_copies_so_callers_cannot_change_the_rules():
    curve = {"breaks": [255, 510], "slopes": [1, 0.5, 0]}
    data = make_file(make_rule(value=curve, levels={"55": {"breaks": [300], "slopes": [1, 0]}}))
    rules = Rules(data)

    got = rules.get("x.y")
    got["breaks"].append(99)
    got["extra"] = True
    assert rules.get("x.y") == {"breaks": [255, 510], "slopes": [1, 0.5, 0]}

    got55 = rules.get("x.y", 55)
    got55["breaks"].append(99)
    assert rules.get("x.y", 55) == {"breaks": [300], "slopes": [1, 0]}

    data["rules"][0]["value"]["breaks"].append(77)  # nor can the dict the rules were built from
    assert rules.get("x.y") == {"breaks": [255, 510], "slopes": [1, 0.5, 0]}


def test_level_must_be_an_integer_so_an_override_is_never_silently_skipped():
    rules = Rules(make_file(make_rule(levels={"55": 20})))
    with pytest.raises(TypeError):
        rules.get("x.y", 55.0)
    with pytest.raises(TypeError):
        rules.get("x.y", "55")


# ---- invalid files fail, with clear messages ----------------------------------------


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_a_rule_missing_a_required_field_is_rejected(field):  # missing seal, source, date, ...
    rule = make_rule()
    del rule[field]
    message = rejection(make_file(rule))
    assert "rules[0]" in message
    assert f"'{field}'" in message


INVALID_RULES = [
    pytest.param({"seal": "wiki"}, ["x.y", "seal", "wiki"], id="unknown-seal"),
    pytest.param({"seal": "Client"}, ["seal", "Client"], id="seal-in-wrong-case"),
    pytest.param({"status": "done"}, ["status", "done"], id="unknown-status"),
    pytest.param({"status": "open"}, ["x.y", "test"], id="open-without-test"),
    pytest.param({"status": "open", "test": "b4"}, ["test", "b4"], id="open-with-lowercase-test"),
    pytest.param({"status": "open", "test": "B123"}, ["test", "B123"], id="test-number-too-long"),
    pytest.param({"test": "T4"}, ["test", "T4"], id="test-id-not-a-b-number"),
    pytest.param({"value": None}, ["x.y", "value", "null"], id="null-value-on-active-rule"),
    pytest.param(
        {"value": None, "status": "superseded"}, ["value", "null"], id="null-value-on-superseded-rule"
    ),
    pytest.param({"date": "2026-13-01"}, ["x.y", "date", "2026-13-01"], id="impossible-month"),
    pytest.param({"date": "2026-02-30"}, ["date", "2026-02-30"], id="impossible-day"),
    pytest.param({"date": "2026-1-5"}, ["date", "2026-1-5"], id="date-not-zero-padded"),
    pytest.param({"date": "2026-10-13T00:00:00"}, ["date"], id="date-with-time"),
    pytest.param({"date": "20261013"}, ["date", "20261013"], id="compact-date"),
    pytest.param({"date": 20261013}, ["date"], id="date-not-a-string"),
    pytest.param({"source": [source(ref="   ")]}, ["source", "blank"], id="blank-source"),
    pytest.param({"source": "unit test"}, ["x.y", "source", "array"], id="source-in-the-old-string-form"),
    pytest.param({"title": ""}, ["title", "blank"], id="empty-title"),
    pytest.param({"unit": " "}, ["unit", "blank"], id="blank-unit"),
    pytest.param({"id": "nodots"}, ["id", "nodots"], id="id-without-a-dot"),
    pytest.param({"id": "Level.current"}, ["id", "Level.current"], id="id-with-uppercase"),
    pytest.param({"id": "level. current"}, ["id"], id="id-with-a-space"),
    pytest.param({"id": "level..current"}, ["id"], id="id-with-an-empty-segment"),
    pytest.param({"id": "level.2nd"}, ["id"], id="id-segment-starting-with-a-digit"),
    pytest.param({"sealed": "model"}, ["x.y", "sealed"], id="unknown-field"),
    pytest.param({"notes": ""}, ["notes", "blank"], id="empty-notes"),
    pytest.param({"levels": {"lvl55": 1}}, ["levels", "lvl55"], id="levels-key-not-a-number"),
    pytest.param({"levels": {}}, ["levels"], id="empty-levels"),
    pytest.param(
        {"alternatives": {"value": 1, "seal": "model", "source": [source()]}},
        ["alternatives"],
        id="alternatives-not-a-list",
    ),
    pytest.param({"alternatives": []}, ["alternatives"], id="empty-alternatives"),
    pytest.param(
        {"alternatives": [{"value": 1, "source": [source()]}]},
        ["alternatives[0]", "seal"],
        id="alternative-without-seal",
    ),
    pytest.param(
        {"alternatives": [{"value": 1, "seal": "wiki", "source": [source()]}]},
        ["alternatives[0].seal", "wiki"],
        id="alternative-with-unknown-seal",
    ),
    pytest.param(
        {"alternatives": [{"value": 1, "seal": "model"}]},
        ["alternatives[0]", "source"],
        id="alternative-without-source",
    ),
    pytest.param(
        {"alternatives": [{"seal": "model", "source": [source()]}]},
        ["alternatives[0]", "value"],
        id="alternative-without-value",
    ),
    pytest.param(
        {"alternatives": [{"value": 1, "seal": "model", "source": [source()], "date": "2026-10-13"}]},
        ["alternatives[0]", "date"],
        id="alternative-with-extra-field",
    ),
    pytest.param(
        {"alternatives": [{"value": 1, "seal": "model", "source": "s"}]},
        ["alternatives[0].source", "array"],
        id="alternative-source-in-the-old-string-form",
    ),
]


@pytest.mark.parametrize(("overrides", "fragments"), INVALID_RULES)
def test_an_invalid_rule_is_rejected_with_a_clear_message(overrides, fragments):
    message = rejection(make_file(make_rule(**overrides)))
    for fragment in fragments:
        assert fragment in message, message


INVALID_FILES = [
    pytest.param([], ["object"], id="root-is-not-an-object"),
    pytest.param({"rules": [make_rule()]}, ["version"], id="missing-version"),
    pytest.param({"version": "2026-10-13"}, ["rules"], id="missing-rules"),
    pytest.param(make_file(make_rule(), version="2026-13-01"), ["version", "2026-13-01"], id="impossible-version"),
    pytest.param({"version": "2026-10-13", "rules": {}}, ["rules"], id="rules-not-a-list"),
    pytest.param(make_file(), ["rules"], id="no-rules-at-all"),
    pytest.param({**make_file(make_rule()), "extra": 1}, ["extra"], id="unknown-top-level-field"),
    pytest.param(make_file("x.y"), ["rules[0]", "object"], id="rule-is-not-an-object"),
]


@pytest.mark.parametrize(("data", "fragments"), INVALID_FILES)
def test_a_malformed_file_is_rejected_with_a_clear_message(data, fragments):
    message = rejection(data)
    for fragment in fragments:
        assert fragment in message, message


@pytest.mark.parametrize("second", [{}, {"status": "superseded"}], ids=["both-active", "second-superseded"])
def test_duplicate_ids_are_rejected_and_both_positions_named(second):
    message = rejection(make_file(make_rule(), make_rule(value=18, **second)))
    assert "duplicate" in message
    assert "'x.y'" in message
    assert "rules[0]" in message
    assert "rules[1]" in message


def test_every_problem_is_reported_at_once():
    data = make_file(
        make_rule(seal="wiki"),
        make_rule(id="a.b", date="2026-13-01"),
        make_rule(id="a.b"),
    )
    with pytest.raises(RulesError) as info:
        Rules(data)
    problems = info.value.problems
    assert len(problems) == 3
    assert any("wiki" in p for p in problems)
    assert any("2026-13-01" in p for p in problems)
    assert any("duplicate" in p for p in problems)
    assert all(p in str(info.value) for p in problems)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(make_file(make_rule(date="2026-1-5")), id="rule-date"),
        pytest.param(make_file(make_rule(), version="nope"), id="file-version"),
    ],
)
def test_one_defect_is_reported_once(data):
    # A malformed date breaks both the 'pattern' and the 'date' format of the schema;
    # the loader must still list it as a single problem.
    with pytest.raises(RulesError) as info:
        Rules(data)
    assert len(info.value.problems) == 1, info.value.problems


def test_rules_error_is_a_valueerror():
    with pytest.raises(ValueError):
        Rules(make_file(make_rule(seal="wiki")))


# ---- valid variants must not be over-rejected ---------------------------------------


def test_an_open_rule_may_have_a_null_value_when_it_names_its_test():
    rules = Rules(make_file(make_rule(status="open", value=None, test="B4")))
    assert rules.get("x.y") is None


def test_a_rule_with_every_optional_field_is_accepted():
    rule = make_rule(
        levels={"55": 20},
        test="B4",
        notes="why this value",
        alternatives=[{"value": {"k": [1, 2]}, "seal": "player", "source": [source(ref="somewhere")]}],
    )
    assert Rules(make_file(rule)).get("x.y", 55) == 20


@pytest.mark.parametrize(
    "value", [0, 1.5, -3, False, True, "text", "", [], [1, 2], {}, {"k": [1, None]}]
)
def test_an_active_rule_may_hold_any_non_null_json_value(value):
    result = Rules(make_file(make_rule(value=value))).get("x.y")
    assert result == value
    assert type(result) is type(value)  # False must not come back as 0


@pytest.mark.parametrize("rule_id", ["naked.cap", "other.cap"])
@pytest.mark.parametrize("status", ["active", "superseded"])
def test_no_rule_id_is_exempt_from_the_null_rule(rule_id, status):
    # naked.cap used to be the one active rule allowed a null value ("there is no cap").
    # Its value is now the string "none", so null belongs to open rules alone, whatever the id.
    message = rejection(make_file(make_rule(id=rule_id, value=None, status=status)))
    assert rule_id in message and "null" in message


def test_the_schema_alone_has_no_exemption_from_the_null_rule_either():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    for rule_id in ("naked.cap", "other.cap"):
        assert list(validator.iter_errors(make_file(make_rule(id=rule_id, value=None)))) != [], rule_id
    open_one = make_rule(id="naked.cap", status="open", value=None, test="B4")
    assert list(validator.iter_errors(make_file(open_one))) == []


# ---- the loader reads strict JSON ---------------------------------------------------


def test_load_reads_a_file_given_as_path_or_str(tmp_path):
    path = write(tmp_path, json.dumps(make_file(make_rule())))
    assert load(path).get("x.y") == 17
    assert load(str(path)).get("x.y") == 17


def test_load_names_the_file_in_validation_errors(tmp_path):
    path = write(tmp_path, json.dumps(make_file(make_rule(seal="wiki"))))
    with pytest.raises(RulesError) as info:
        load(path)
    assert str(path) in str(info.value)
    assert "wiki" in str(info.value)


def test_load_rejects_invalid_json(tmp_path):
    with pytest.raises(RulesError, match="not valid JSON"):
        load(write(tmp_path, "{"))


def test_load_rejects_duplicate_keys_that_a_json_parser_would_silently_merge(tmp_path):
    text = (
        '{"version": "2026-10-13", "rules": [{"id": "x.y", "title": "t", "value": 1, "unit": "u", '
        '"seal": "model", "seal": "client", "source": "s", "date": "2026-10-13", "status": "active"}]}'
    )
    with pytest.raises(RulesError, match="duplicate key 'seal'"):
        load(write(tmp_path, text))


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_load_rejects_numbers_that_are_not_json(tmp_path, constant):
    text = (
        '{"version": "2026-10-13", "rules": [{"id": "x.y", "title": "t", "value": CONST, "unit": "u", '
        '"seal": "model", "source": "s", "date": "2026-10-13", "status": "active"}]}'
    ).replace("CONST", constant)
    with pytest.raises(RulesError, match=constant):
        load(write(tmp_path, text))


def test_load_rejects_bytes_that_are_not_utf8(tmp_path):
    path = tmp_path / "rules.json"
    path.write_bytes(b'{"version": "\xff"}')
    with pytest.raises(RulesError, match="UTF-8"):
        load(path)


def test_load_of_a_missing_file_raises_filenotfounderror(tmp_path):
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope.json")


# ---- the content of the real file ---------------------------------------------------


def test_rule_ids_match_the_expected_ids(raw):
    ids = [rule["id"] for rule in raw["rules"]]
    assert len(set(EXPECTED_IDS)) == len(EXPECTED_IDS), "the expected list itself has a duplicate"
    assert len(ids) == len(set(ids)), "duplicate ids in rules.json"
    assert sorted(set(EXPECTED_IDS) - set(ids)) == [], "rules dropped from rules.json"
    assert sorted(set(ids) - set(EXPECTED_IDS)) == [], "rules in rules.json that are not in EXPECTED_IDS"


def test_every_open_rule_names_a_b_test(raw):
    open_rules = [rule for rule in raw["rules"] if rule["status"] == "open"]
    assert open_rules, "the v0 file is expected to carry open rules"
    for rule in open_rules:
        assert re.fullmatch(r"B\d{1,2}", rule.get("test", "")), rule["id"]


def test_every_alternative_has_value_seal_and_source(raw):
    with_alternatives = {rule["id"]: rule for rule in raw["rules"] if "alternatives" in rule}
    assert RULES_WITH_ALTERNATIVES <= set(with_alternatives)
    for rule_id, rule in with_alternatives.items():
        assert rule["alternatives"], rule_id
        for alternative in rule["alternatives"]:
            assert set(alternative) == {"value", "seal", "source"}, rule_id
            assert alternative["seal"] in SEALS, rule_id
            assert source_defects(alternative["source"]) == [], rule_id  # the list form


def test_mana_wis_bands_is_settled_by_the_in_game_reading_of_2026_10_27(raw):
    rule = next(r for r in raw["rules"] if r["id"] == "mana.wis_bands")
    assert rule["value"] == {"breaks": [100, 200, 510], "slopes": [1, 2.5, 1.25, 0]}  # one slope from 200 to 510
    assert (rule["seal"], rule["status"], rule["date"]) == ("measured", "active", "2026-10-27")
    assert "test" not in rule and "alternatives" not in rule  # B4 is done, and the 0.654 reading is ruled out
    assert ("private-measured", PRIVATE_LABEL) in [(x["kind"], x["ref"]) for x in rule["source"]]
    assert not any(ch.isdigit() for ch in rule["notes"])  # a private source keeps digits out of the notes


def test_in_the_real_file_a_null_value_belongs_to_open_rules_alone(raw):
    # naked.cap was the one exception until it became the string "none".
    nulls = {rule["id"] for rule in raw["rules"] if rule["value"] is None and rule["status"] != "open"}
    assert nulls == set()


def test_every_rule_of_the_real_file_is_reachable_through_get_and_seal(raw):
    rules = load(RULES_PATH)
    for rule in raw["rules"]:
        expected = rule.get("levels", {}).get("50", rule["value"])
        assert rules.get(rule["id"]) == expected, rule["id"]
        assert rules.seal(rule["id"]) == rule["seal"], rule["id"]
        assert rules.seal(rule["id"]) in SEALS, rule["id"]
        assert rules.sources(rule["id"]) == rule["source"], rule["id"]


# ---- sources are public-only --------------------------------------------------------
#
# A rule's source is a list of {"kind", "ref"} objects: a public https URL, a shipped
# client text file, a public statement without a URL, or the fixed label for the
# maintainer's own observations. Nothing public may cite a client binary, and a rule
# that rests on a private observation says nothing numeric about it in its notes.

GOOD_SOURCE_LISTS = [
    pytest.param([source("url", "https://github.com/EQEmu/Server")], id="url"),
    pytest.param([source("url", "https://eqlwiki.com/")], id="url-with-a-slash-as-path"),
    pytest.param([source("url", "https://eqlwiki.com")], id="url-without-a-path"),
    pytest.param(
        [source("url", "https://eqlwiki.com/Item_Upgrade_System?oldid=1#top")],
        id="url-with-query-and-fragment",
    ),
    *[pytest.param([source("client-file", name)], id=f"client-file-{name}") for name in sorted(CLIENT_FILES)],
    pytest.param([source("public-text", "developer hotfix notes 2026-07-29")], id="public-text"),
    pytest.param([source("public-text", "observation of reserved words")], id="lowercase-rva-inside-a-word"),
    pytest.param([private("private-measured")], id="private-measured"),
    pytest.param([private("private-player")], id="private-player"),
    pytest.param(
        [source("url", "https://eqltools.com/combat"), private("private-player"), source()],
        id="several-sources",
    ),
]


@pytest.mark.parametrize("sources", GOOD_SOURCE_LISTS)
def test_every_kind_of_source_is_accepted_for_a_rule_and_for_an_alternative(sources):
    alternative = {"value": 1, "seal": "model", "source": sources}
    rules = Rules(make_file(make_rule(source=sources, alternatives=[alternative])))
    assert rules.sources("x.y") == sources


REF = "source[0].ref"  # where the message of a bad ref points

BAD_SOURCE_LISTS = [
    pytest.param("just a string", ["source", "array"], id="old-string-form"),
    pytest.param([], ["source", "non-empty"], id="empty-list"),
    pytest.param(["https://example.org/"], ["source[0]", "object"], id="bare-string-item"),
    pytest.param([{"kind": "url"}], ["source[0]", "'ref'"], id="missing-ref"),
    pytest.param([{"ref": "https://example.org/"}], ["source[0]", "'kind'"], id="missing-kind"),
    pytest.param([source("wiki", "https://example.org/")], ["source[0].kind", "wiki"], id="unknown-kind"),
    pytest.param([source("URL", "https://example.org/")], ["source[0].kind", "URL"], id="kind-in-wrong-case"),
    pytest.param(
        [{**source("url", "https://example.org/"), "note": "x"}], ["source[0]", "note"], id="extra-field"
    ),
    pytest.param([source("public-text", "")], [REF, "blank"], id="empty-public-text"),
    pytest.param([source("public-text", " \n ")], [REF, "blank"], id="blank-public-text"),
    pytest.param([source("public-text", 5)], [REF, "string"], id="ref-not-a-string"),
    # url: https, a host, no spaces, no user name, no port
    pytest.param([source("url", "http://example.org/")], [REF, "https"], id="http-not-https"),
    pytest.param([source("url", "example.org")], [REF, "https"], id="url-without-a-scheme"),
    pytest.param([source("url", "ftp://example.org/")], [REF, "https"], id="ftp"),
    pytest.param([source("url", "HTTPS://example.org/")], [REF, "https"], id="scheme-in-capitals"),
    pytest.param([source("url", "https://")], [REF, "https"], id="url-without-a-host"),
    pytest.param([source("url", "https:///path")], [REF, "https"], id="url-with-an-empty-host"),
    pytest.param([source("url", "https://example.org/a b")], [REF, "https"], id="space-in-url"),
    pytest.param([source("url", " https://example.org/")], [REF, "https"], id="leading-space-in-url"),
    pytest.param([source("url", "https://example.org/\n")], [REF, "https"], id="trailing-newline-in-url"),
    pytest.param([source("url", "https://user@example.org/")], [REF, "https"], id="user-name-in-url"),
    pytest.param([source("url", "https://example.org:8080/")], [REF, "https"], id="port-in-url"),
    pytest.param([source("url", "   ")], [REF, "blank"], id="blank-url"),
    # client-file: exactly the shipped text files
    pytest.param(
        [source("client-file", "Resources/Other.txt")], [REF, "Resources/Other.txt"], id="client-file-not-listed"
    ),
    pytest.param(
        [source("client-file", "resources/basedata.txt")],
        [REF, "resources/basedata.txt"],
        id="client-file-in-wrong-case",
    ),
    pytest.param(
        [source("client-file", "Resources/basedata.txt ")],
        [REF, "basedata.txt "],
        id="client-file-with-a-trailing-space",
    ),
    pytest.param(
        [source("client-file", "basedata.txt")], [REF, "'basedata.txt'"], id="client-file-without-its-folder"
    ),
    # private-*: exactly the fixed label, never a count, a value or a date
    pytest.param(
        [source("private-measured", "seen 1,309 times")],
        [REF, PRIVATE_LABEL],
        id="private-measured-with-a-count",
    ),
    pytest.param(
        [source("private-player", "a friend said so on 2026-10-12")],
        [REF, PRIVATE_LABEL],
        id="private-player-with-a-date",
    ),
    pytest.param(
        [source("private-measured", "")], [REF, PRIVATE_LABEL], id="private-measured-without-a-label"
    ),
    pytest.param(
        [source("private-measured", PRIVATE_LABEL.upper())], [REF, PRIVATE_LABEL], id="private-label-in-capitals"
    ),
]


@pytest.mark.parametrize(("sources", "fragments"), BAD_SOURCE_LISTS)
def test_a_bad_source_is_rejected_with_a_clear_message(sources, fragments):
    message = rejection(make_file(make_rule(source=sources)))
    assert "x.y" in message, message
    for fragment in fragments:
        assert fragment in message, message


@pytest.mark.parametrize(("sources", "fragments"), BAD_SOURCE_LISTS)
def test_a_bad_alternative_source_is_rejected_the_same_way(sources, fragments):  # same list form
    alternative = {"value": 1, "seal": "model", "source": sources}
    message = rejection(make_file(make_rule(alternatives=[alternative])))
    assert "alternatives[0].source" in message, message
    for fragment in fragments:
        assert fragment in message, message


@pytest.mark.parametrize(("sources", "fragments"), BAD_SOURCE_LISTS)
def test_the_schema_alone_rejects_a_bad_source(sources, fragments):
    # The source forms are a schema check: every tool that reads the schema gets them,
    # not only the Python loader.
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    alternative = {"value": 1, "seal": "model", "source": sources}
    assert list(validator.iter_errors(make_file(make_rule(source=sources)))) != []
    assert list(validator.iter_errors(make_file(make_rule(alternatives=[alternative])))) != []


FORBIDDEN_REFS = [
    pytest.param(source("public-text", "eqgame table"), id="eqgame"),
    pytest.param(source("public-text", "EQGame.EXE tables"), id="eqgame-exe-in-any-case"),
    pytest.param(source("public-text", "loader.exe"), id="exe"),
    pytest.param(source("public-text", "loader.EXE"), id="exe-in-capitals"),
    pytest.param(source("public-text", "the RVA of the table"), id="rva"),
    pytest.param(source("public-text", "table at offset 12"), id="offset"),
    pytest.param(source("public-text", "Offset table"), id="offset-capitalised"),
    pytest.param(source("public-text", "address 0x1F"), id="hex-address"),
    pytest.param(source("public-text", "address 0X1F"), id="hex-address-with-capital-x"),
    pytest.param(source("url", "https://example.org/eqgame"), id="eqgame-in-a-url"),
    pytest.param(source("url", "https://example.org/offset"), id="offset-in-a-url"),
    pytest.param(source("client-file", "eqgame.exe"), id="the-client-binary-as-a-client-file"),
]


@pytest.mark.parametrize("entry", FORBIDDEN_REFS)
def test_a_ref_that_cites_a_client_binary_is_rejected(entry):
    alternative = {"value": 1, "seal": "model", "source": [entry]}
    for rule in (make_rule(source=[entry]), make_rule(alternatives=[alternative])):
        message = rejection(make_file(rule))
        assert ".ref" in message and "client binary" in message, message
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(make_file(make_rule(source=[entry])))) != []


NOTES_WITH_DIGITS = [
    pytest.param("seen 3 times", id="count"),
    pytest.param("measured on 2026-10-12", id="date"),
    pytest.param("about 0.15% off", id="percentage"),
    pytest.param("1,309 drops", id="thousands"),
    pytest.param("+1 per tier", id="signed-value"),
    pytest.param("a3", id="digit-inside-a-word"),
    # Not [0-9], yet still numbers; built with chr() so that this file stays plain ASCII.
    pytest.param("three " + chr(0xFF13), id="fullwidth-digit"),
    pytest.param("three " + chr(0x0663), id="arabic-indic-digit"),
    pytest.param("squared " + chr(0x00B2), id="superscript-digit"),
    pytest.param("a half " + chr(0x00BD), id="vulgar-fraction"),
    pytest.param("level " + chr(0x2167), id="roman-numeral"),
]


@pytest.mark.parametrize("kind", ["private-measured", "private-player"])
@pytest.mark.parametrize("notes", NOTES_WITH_DIGITS)
def test_a_private_source_forbids_digits_in_notes(kind, notes):
    rule = make_rule(source=[source("url", "https://example.org/"), private(kind)], notes=notes)
    message = rejection(make_file(rule))
    for fragment in ("x.y", "notes", "digit", kind):
        assert fragment in message, message


def test_a_private_alternative_source_forbids_digits_in_notes_too():
    alternative = {"value": 1, "seal": "player", "source": [private("private-player")]}
    message = rejection(make_file(make_rule(alternatives=[alternative], notes="seen 3 times")))
    for fragment in ("x.y", "notes", "digit", "private-player"):
        assert fragment in message, message


@pytest.mark.parametrize(
    "sources",
    [
        pytest.param([private()], id="private-measured"),
        pytest.param(
            [source("url", "https://example.org/"), private("private-player")], id="url-and-private-player"
        ),
    ],
)
def test_a_private_source_is_fine_with_notes_that_hold_no_digit(sources):
    rule = make_rule(source=sources, notes="Player-reported; not applied.")
    assert Rules(make_file(rule)).sources("x.y") == sources
    assert Rules(make_file(make_rule(source=sources))).sources("x.y") == sources  # and with no notes at all


def test_digits_in_notes_are_fine_when_no_source_is_private():
    sources = [
        source("url", "https://eqltools.com/combat"),
        source("client-file", "dbstr_us.txt"),
        source("public-text", "patch notes 2026-09-22"),
    ]
    alternative = {"value": 1, "seal": "model", "source": [source("url", "https://example.org/")]}
    rule = make_rule(source=sources, alternatives=[alternative], notes="threshold of about 34, patch 2026-09-22")
    assert Rules(make_file(rule)).sources("x.y") == sources


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"source": None}, id="source-null"),
        pytest.param({"source": [None]}, id="source-item-null"),
        pytest.param({"source": [{"kind": ["private-measured"], "ref": "x"}]}, id="kind-a-list"),
        pytest.param({"source": [{"kind": 5, "ref": 5}]}, id="kind-a-number"),
        pytest.param({"source": [private()], "notes": 3}, id="notes-a-number"),
        pytest.param({"alternatives": [None]}, id="alternative-null"),
        pytest.param(
            {"alternatives": [{"value": 1, "seal": "model", "source": None}]}, id="alternative-source-null"
        ),
        pytest.param({"alternatives": "x"}, id="alternatives-a-string"),
        pytest.param({"alternatives": {"source": [private()]}}, id="alternatives-an-object"),
    ],
)
def test_a_malformed_rule_gets_a_rules_error_and_never_a_crash_in_the_notes_guard(overrides):
    message = rejection(make_file(make_rule(**{"notes": "3", **overrides})))
    assert "x.y" in message


# ---- Rules.sources ------------------------------------------------------------------


def test_sources_returns_the_source_objects_of_the_rule():
    sources = [source("url", "https://example.org/a"), private("private-player")]
    rules = Rules(make_file(make_rule(source=sources)))
    assert rules.sources("x.y") == sources


def test_sources_returns_copies_so_callers_cannot_change_the_rules():
    data = make_file(make_rule(source=[source("url", "https://example.org/a")]))
    rules = Rules(data)

    got = rules.sources("x.y")
    got[0]["ref"] = "https://example.org/changed"
    got.append(source())
    assert rules.sources("x.y") == [source("url", "https://example.org/a")]

    data["rules"][0]["source"][0]["ref"] = "https://example.org/other"  # nor can the dict it was built from
    assert rules.sources("x.y") == [source("url", "https://example.org/a")]


def test_sources_of_an_unknown_or_superseded_rule_raise_keyerror():
    rules = Rules(make_file(make_rule(), make_rule(id="old.rule", status="superseded")))
    with pytest.raises(KeyError):
        rules.sources("no.such.rule")
    with pytest.raises(KeyError):
        rules.sources("old.rule")


# ---- the sources and special rules of the real file ---------------------------------


def rules_by_id(raw):
    return {rule["id"]: rule for rule in raw["rules"]}


def test_every_source_of_the_real_file_has_a_valid_kind_and_ref(raw):
    count = 0
    for where, sources in all_sources(raw):
        assert source_defects(sources) == [], where
        count += len(sources)
    assert count >= len(raw["rules"])


def test_client_file_refs_come_only_from_the_allowed_list(raw):
    cited = {
        entry["ref"] for _, sources in all_sources(raw) for entry in sources if entry["kind"] == "client-file"
    }
    assert cited, "the real file is expected to cite client files"
    assert cited <= CLIENT_FILES, sorted(cited - CLIENT_FILES)


def test_no_ref_mentions_a_client_binary_an_offset_or_a_disassembly(raw):
    refs = [entry["ref"] for _, sources in all_sources(raw) for entry in sources]
    assert refs
    for ref in refs:
        assert forbidden_words_in(ref) == [], ref


def test_the_real_file_as_a_whole_names_no_client_binary_or_offset():  # wider than the refs
    assert forbidden_words_in(RULES_PATH.read_text(encoding="utf-8")) == []


def test_rules_that_rest_on_a_private_observation_have_notes_without_digits(raw):
    private_rules = [rule for rule in raw["rules"] if has_private_source(rule)]
    assert private_rules
    assert any("notes" in rule for rule in private_rules), "no notes to check"
    for rule in private_rules:
        notes = rule.get("notes", "")
        assert not any(character.isnumeric() for character in notes), rule["id"]


def test_monk_weight_curve_replaces_the_weight_threshold(raw):
    rules = rules_by_id(raw)
    assert "monk.weight_threshold" not in rules
    curve = rules["monk.weight_curve"]
    assert curve["value"] == {
        "softcap_stones": 17,
        "hardcap_stones": 36,
        "full_bonus_ac": 73,
        "shape": "EQEmu fade",
    }
    assert curve["levels"] == {"55": {"softcap_stones": 20, "hardcap_stones": 40, "full_bonus_ac": 80, "shape": "EQEmu fade"}}
    assert curve["seal"] == "model"
    assert curve["status"] == "open"
    assert curve["test"] == "B9"
    assert curve["notes"] == "EQL Tools' threshold of about 34 read as the end of the bonus"
    assert curve["alternatives"] == [
        {
            "value": {"full_until_stones": 34},
            "seal": "developer",
            "source": [{"kind": "url", "ref": "https://eqltools.com/combat"}],
        }
    ]


def test_monk_weight_curve_is_read_through_the_loader_at_both_levels():
    rules = load(RULES_PATH)
    assert rules.get("monk.weight_curve") == {
        "softcap_stones": 17,
        "hardcap_stones": 36,
        "full_bonus_ac": 73,
        "shape": "EQEmu fade",
    }
    assert rules.get("monk.weight_curve", 55) == {"softcap_stones": 20, "hardcap_stones": 40, "full_bonus_ac": 80, "shape": "EQEmu fade"}
    assert rules.seal("monk.weight_curve") == "model"
    with pytest.raises(KeyError):
        rules.get("monk.weight_threshold")


def test_iksar_ac_placement_is_open_until_test_b17(raw):
    placement = rules_by_id(raw)["race.iksar_ac_placement"]
    assert placement["test"] == "B17"
    assert placement["status"] == "open"


def test_rule_sources_match_the_expected_sources(raw):
    actual = {rule["id"]: [(entry["kind"], entry["ref"]) for entry in rule["source"]] for rule in raw["rules"]}
    assert sorted(set(EXPECTED_SOURCES) - set(actual)) == []
    assert sorted(set(actual) - set(EXPECTED_SOURCES)) == []
    for rule_id, expected in EXPECTED_SOURCES.items():
        assert actual[rule_id] == expected, rule_id


def test_alternative_sources_match_the_expected_sources(raw):
    actual = {
        rule["id"]: [
            [(entry["kind"], entry["ref"]) for entry in alternative["source"]]
            for alternative in rule["alternatives"]
        ]
        for rule in raw["rules"]
        if "alternatives" in rule
    }
    assert actual == EXPECTED_ALTERNATIVE_SOURCES


def test_weapon_damage_is_ten_percent_with_the_wiki_figure_as_its_alternative(raw):
    rule = rules_by_id(raw)["tier.weapon_damage_pct"]
    assert (rule["value"], rule["status"], rule["test"]) == (10, "active", "B5")
    assert [alternative["value"] for alternative in rule["alternatives"]] == [5]


def test_dual_wield_factor_is_a_model_value_for_each_kind_of_trio_open_until_test_b5(raw):
    # The chance that an off-hand swing comes: the profile reads the value for its trio and the weapon index gets it.
    rule = rules_by_id(raw)["weapons.dual_wield_factor"]
    assert (rule["value"], rule["seal"]) == ({"with_monk": 0.83, "without_monk": 0.69}, "model")
    assert (rule["status"], rule["test"]) == ("open", "B5")
    assert rule["source"] == [{"kind": "url", "ref": "https://eqlwiki.com/Skill_Dual_Wield"}]
    assert load(RULES_PATH).get("weapons.dual_wield_factor") == {"with_monk": 0.83, "without_monk": 0.69}


def test_weapon_damage_weight_is_a_model_value_open_until_test_b18(raw):
    # roles.weights_for multiplies it by each role template's ATK weight (the Caster template uses 0); in-game test
    # B18 (a melee parse with two weapons of known damage index at the same ATK) will settle it.
    rule = rules_by_id(raw)["weapons.damage_weight"]
    assert (rule["value"], rule["unit"], rule["seal"]) == (
        600, "HP-equivalents per damage-index point per unit of the role's ATK weight", "model"
    )  # fmt: skip
    assert (rule["status"], rule["test"]) == ("open", "B18")
    assert rule["source"] == [{"kind": "public-text", "ref": "TrioForge judgment"}]
    assert rule["notes"] == (
        "Multiplied by each role template's ATK weight; the Caster role uses 0. "
        "One ATK point is taken as worth about a tenth of a percent of melee damage."
    )
    assert not has_private_source(rule)  # so the digit in the notes is allowed
    loaded = load(RULES_PATH)
    assert (loaded.get("weapons.damage_weight"), loaded.seal("weapons.damage_weight")) == (600, "model")


def test_naked_cap_is_the_string_none_and_still_active(raw):
    assert load(RULES_PATH).get("naked.cap") == "none"
    rule = rules_by_id(raw)["naked.cap"]
    assert rule["value"] == "none"
    assert rule["status"] == "active"
    assert rule["seal"] == "measured"
    assert rule["notes"] == "EQL Tools' naked cap is player-reported; not applied"


def test_naked_rule_is_sealed_as_player_reports_now_that_no_client_binary_is_cited(raw):
    assert rules_by_id(raw)["naked.rule"]["seal"] == "player"


def test_the_softcap_rate_is_read_per_class_from_the_client_table_it_is_not_one_number(raw):
    # the rate past the softcap is one of the columns of ACMitigation.txt, and it differs by class: the profile reads the
    # table, so the rule says where it comes from and keeps the number only as an example
    rule = rules_by_id(raw)["ac.softcap.past_cap_rate"]
    assert rule["value"] == "per class from Resources/ACMitigation.txt: the rate of the class with the best softcap"
    assert (rule["unit"], rule["seal"], rule["status"]) == ("text", "client", "active")
    assert rule["notes"] == "For example 0.33 for the Paladin at level 50."
    assert rule["source"] == [{"kind": "client-file", "ref": "Resources/ACMitigation.txt"}]
    assert not has_private_source(rule)  # so the digits in the notes are allowed
    assert load(RULES_PATH).get("ac.softcap.past_cap_rate") == rule["value"]


def test_the_endurance_formula_says_that_the_factors_are_per_class(raw):
    rule = rules_by_id(raw)["end.formula"]
    assert rule["value"] == (
        "per pool: base_end + end_fac x converted(avg(STR,STA,DEX,AGI)), base_end and end_fac per class; best two pools"
    )
    assert rule["unit"] == "text" and "3.25" not in rule["value"]  # not one factor for every class


# ---- end-of-string anchors ----------------------------------------------------------
#
# Python's $ also matches before a trailing newline, so a pattern that ends in $ lets
# "x.y\n" through. Every pattern of the schema ends in (?![\s\S]) instead.


def schema_patterns(node):
    """Every regular expression of a schema: the 'pattern' values and the 'patternProperties' keys."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "pattern" and isinstance(value, str):
                found.append(value)
            elif key == "patternProperties" and isinstance(value, dict):
                found.extend(value)
            found.extend(schema_patterns(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(schema_patterns(item))
    return found


def test_no_pattern_of_the_schema_is_anchored_with_a_dollar_sign():
    patterns = schema_patterns(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    assert len(patterns) >= 7, patterns  # the scan does find the patterns (dates, ids, refs, levels, ...)
    for pattern in patterns:
        assert not re.search(r"(?<!\\)\$", pattern), pattern


TRAILING_NEWLINES = [
    pytest.param(make_file(make_rule(id="x.y\n")), "id", id="rule-id"),
    pytest.param(make_file(make_rule(date="2026-10-13\n")), "date", id="rule-date"),
    pytest.param(make_file(make_rule(), version="2026-10-13\n"), "version", id="file-version"),
    pytest.param(make_file(make_rule(status="open", test="B4\n")), "test", id="test-id"),
    pytest.param(make_file(make_rule(levels={"55\n": 20})), "levels", id="level-key"),
]


@pytest.mark.parametrize(("data", "field"), TRAILING_NEWLINES)
def test_a_trailing_newline_is_rejected_by_the_loader(data, field):
    assert field in rejection(data)


@pytest.mark.parametrize(("data", "field"), TRAILING_NEWLINES)
def test_a_trailing_newline_is_rejected_by_the_schema_alone(data, field):
    # No format checker here: the 'date' format would reject some of these on its own, and the
    # point is that the patterns do, for every tool that reads only the schema.
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(data)) != []


# ---- level keys, level values and the level argument --------------------------------

BAD_LEVEL_KEYS = [
    pytest.param("0", id="zero"),
    pytest.param("00", id="two-zeros"),
    pytest.param("01", id="leading-zero"),
    pytest.param("05", id="leading-zero-before-a-digit"),
    pytest.param("100", id="three-digits"),
    pytest.param("-1", id="negative"),
    pytest.param("+5", id="plus-sign"),
    pytest.param("5.0", id="decimal-point"),
    pytest.param("1e1", id="exponent"),
    pytest.param(" 5", id="leading-space"),
    pytest.param("5 ", id="trailing-space"),
    pytest.param("5\n", id="trailing-newline"),
    pytest.param("", id="empty"),
    pytest.param("lvl55", id="letters"),
    # Not [0-9], yet still digits; built with chr() so that this file stays plain ASCII.
    pytest.param(chr(0x0665), id="arabic-indic-digit"),
    pytest.param(chr(0xFF15), id="fullwidth-digit"),
]


@pytest.mark.parametrize("key", BAD_LEVEL_KEYS)
def test_a_level_key_that_is_not_a_whole_number_from_1_to_99_is_rejected(key):
    message = rejection(make_file(make_rule(levels={key: 20})))
    assert "levels" in message and repr(key) in message, message


@pytest.mark.parametrize("key", BAD_LEVEL_KEYS)
def test_the_schema_alone_rejects_a_bad_level_key(key):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(make_file(make_rule(levels={key: 20})))) != []


@pytest.mark.parametrize("key", ["1", "9", "10", "50", "55", "99"])
def test_level_keys_from_1_to_99_are_accepted(key):
    rules = Rules(make_file(make_rule(levels={key: 20})))
    assert rules.get("x.y", int(key)) == 20


def test_a_level_key_that_is_not_a_string_is_rejected():
    # The key pattern only judges strings, and get() looks a level up by its text: an int key
    # would never be found, so its override would be skipped without a word.
    message = rejection(make_file(make_rule(levels={55: 20})))
    assert "levels" in message and "string" in message, message


@pytest.mark.parametrize("status", ["active", "superseded"])
def test_a_null_level_value_is_rejected_on_a_settled_rule(status):
    message = rejection(make_file(make_rule(status=status, levels={"50": 1, "55": None})))
    for fragment in ("x.y", "levels", "55", "null"):
        assert fragment in message, message


def test_a_null_level_value_is_fine_on_an_open_rule():
    rules = Rules(make_file(make_rule(status="open", test="B4", levels={"55": None})))
    assert rules.get("x.y", 55) is None
    assert rules.get("x.y", 50) == 17


@pytest.mark.parametrize("value", [0, 0.0, False, "", [], {}], ids=repr)
def test_a_level_value_that_is_falsy_but_not_null_is_fine(value):
    result = Rules(make_file(make_rule(levels={"55": value}))).get("x.y", 55)
    assert result == value and type(result) is type(value)


def test_the_schema_alone_has_the_null_rule_for_level_values_too():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    assert list(validator.iter_errors(make_file(make_rule(levels={"55": None})))) != []
    assert list(validator.iter_errors(make_file(make_rule(status="open", test="B4", levels={"55": None})))) == []


@pytest.mark.parametrize("level", [True, False])
def test_get_rejects_a_bool_level(level):
    # True is the integer 1 to Python: it would silently pick the level-1 override.
    rules = Rules(make_file(make_rule(levels={"1": 5})))
    with pytest.raises(TypeError):
        rules.get("x.y", level)


@pytest.mark.parametrize("level", [-1, -50, -(10**30)], ids=["minus-1", "minus-50", "minus-a-huge-number"])
def test_get_rejects_a_negative_level(level):
    rules = Rules(make_file(make_rule(levels={"55": 20})))
    with pytest.raises(ValueError):
        rules.get("x.y", level)


@pytest.mark.parametrize("level", [None, [55], 55.0, 55.5, "55", b"55"], ids=repr)
def test_get_rejects_a_level_that_is_not_an_integer(level):
    rules = Rules(make_file(make_rule(levels={"55": 20})))
    with pytest.raises(TypeError):
        rules.get("x.y", level)


@pytest.mark.parametrize("level", [0, 100, 10_000])
def test_a_level_that_no_key_can_name_gets_the_plain_value(level):
    # Keys run from "1" to "99". get() refuses a level only when it is not an integer or is
    # negative; one that merely has no override gets the value, as level 60 does in
    # test_levels_override_value_only_at_their_level.
    assert Rules(make_file(make_rule(levels={"55": 20}))).get("x.y", level) == 17


# ---- numbers and nesting: strict JSON, from text and from memory --------------------

# Where a value can sit in a rule; each entry turns a value into the overrides for make_rule.
PLACES = {
    "value": lambda v: {"value": v},
    "nested-in-value": lambda v: {"value": {"k": [1, {"deeper": v}]}},
    "level-value": lambda v: {"levels": {"55": v}},
    "alternative-value": lambda v: {"alternatives": [{"value": v, "seal": "model", "source": [source()]}]},
}


def text_with(literal, **overrides):
    """A rules file as JSON text, with ``literal`` pasted in where the rule holds the string "@@".

    Lets a test put into the text what no Python value could stand for, such as 1e999 or a
    bracket repeated ten thousand times.
    """
    return json.dumps(make_file(make_rule(**overrides))).replace('"@@"', literal)


def nested_list(depth):
    deep = []
    for _ in range(depth):
        deep = [deep]
    return deep


@pytest.mark.parametrize("place", PLACES)
@pytest.mark.parametrize(
    ("literal", "overflowing"),
    [
        ("1e999", "1e999"),
        ("-1e999", "-1e999"),
        ("1E400", "1E400"),
        ("[1, 2e999]", "2e999"),
        ('{"k": [0.5, -1e999]}', "-1e999"),
    ],
)
def test_load_rejects_a_float_that_overflows_to_infinity(tmp_path, literal, overflowing, place):
    # The parser names the literal itself; the walk over the finished data, which would also
    # catch the infinity, can only say "inf". Both are a RulesError, so only the first quotes it.
    with pytest.raises(RulesError, match="finite") as info:
        load(write(tmp_path, text_with(literal, **PLACES[place]("@@"))))
    assert overflowing in str(info.value)


@pytest.mark.parametrize("place", PLACES)
@pytest.mark.parametrize(
    "literal",
    ["1234567890123456", "-1234567890123456", "9" * 40, "1" + "0" * 5000, "[7, 1234567890123456]"],
    ids=["16-digits", "minus-16-digits", "40-digits", "5001-digits", "in-a-list"],
)
def test_load_rejects_an_integer_of_more_than_15_digits(tmp_path, literal, place):
    with pytest.raises(RulesError, match="15 digits"):
        load(write(tmp_path, text_with(literal, **PLACES[place]("@@"))))


def test_the_message_for_a_huge_integer_does_not_repeat_it(tmp_path):
    with pytest.raises(RulesError) as info:
        load(write(tmp_path, text_with("1" + "0" * 5000, value="@@")))
    assert len(str(info.value)) < 500


@pytest.mark.parametrize("literal", ["123456789012345", "-123456789012345", "0", "-0"])
def test_load_accepts_integers_of_up_to_15_digits(tmp_path, literal):
    path = write(tmp_path, text_with(literal, value="@@"))
    assert load(path).get("x.y") == int(literal)


@pytest.mark.parametrize("literal", ["1e300", "-1e300", "1e-999", "0.1234567890123456789"])
def test_load_accepts_floats_that_are_finite(tmp_path, literal):
    path = write(tmp_path, text_with(literal, value="@@"))
    assert load(path).get("x.y") == float(literal)


@pytest.mark.parametrize("shape", ["list", "object"])
@pytest.mark.parametrize("depth", [1500, 10_000])
def test_load_turns_nesting_that_is_too_deep_into_a_rules_error(tmp_path, depth, shape):
    # json.loads raises RecursionError for the deeper one; the shallower one it still reads, and the
    # checks that follow must not leak the same error.
    literal = "[" * depth + "]" * depth if shape == "list" else '{"a": ' * depth + "1" + "}" * depth
    with pytest.raises(RulesError, match="nested"):
        load(write(tmp_path, text_with(literal, value="@@")))


def test_load_turns_a_stray_valueerror_of_the_json_reader_into_a_rules_error(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("boom")

    stub = types.SimpleNamespace(loads=boom, JSONDecodeError=json.JSONDecodeError)
    monkeypatch.setattr(rules_module, "json", stub)
    with pytest.raises(RulesError, match="boom"):
        load(write(tmp_path, "{}"))


@pytest.mark.parametrize("place", PLACES)
@pytest.mark.parametrize(
    "number",
    [float("nan"), float("inf"), -float("inf"), 1e999],
    ids=["nan", "inf", "minus-inf", "overflowing-literal"],
)
def test_rules_built_in_memory_reject_a_float_that_is_not_finite(number, place):
    message = rejection(make_file(make_rule(**PLACES[place](number))))
    assert "x.y" in message and "finite" in message, message


@pytest.mark.parametrize("place", PLACES)
@pytest.mark.parametrize(
    "number",
    [10**15, -(10**15), 10**5000, -(10**5000)],
    ids=["16-digits", "minus-16-digits", "5001-digits", "minus-5001-digits"],
)
def test_rules_built_in_memory_reject_an_integer_of_more_than_15_digits(number, place):
    message = rejection(make_file(make_rule(**PLACES[place](number))))
    assert "x.y" in message and "15 digits" in message, message


@pytest.mark.parametrize("place", PLACES)
@pytest.mark.parametrize(
    "number",
    [10**15 - 1, -(10**15 - 1), 0, 1e300, -1e300, True],
    ids=["15-digits", "minus-15-digits", "zero", "big-float", "minus-big-float", "bool"],
)
def test_rules_built_in_memory_accept_what_json_can_carry_exactly(number, place):
    Rules(make_file(make_rule(**PLACES[place](number))))


@pytest.mark.parametrize("depth", [1500, 10_000])
def test_rules_built_in_memory_reject_a_value_nested_too_deeply(depth):
    message = rejection(make_file(make_rule(value=nested_list(depth))))
    assert "nested" in message, message


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(make_file(make_rule(title=10**5000)), id="title"),
        pytest.param(make_file(make_rule(seal=10**5000)), id="seal"),
        pytest.param(make_file(make_rule(id=10**5000)), id="id"),
        pytest.param(make_file(make_rule(date=10**5000)), id="date"),
        pytest.param(make_file(make_rule(), version=10**5000), id="version"),
    ],
)
def test_a_huge_integer_where_text_belongs_is_a_rules_error_not_a_crash(data):
    # jsonschema quotes the offending value in its message, and Python refuses to print an
    # integer of thousands of digits; that ValueError must not escape.
    message = rejection(data)
    assert "15 digits" in message, message


def test_rules_built_in_memory_reject_a_value_that_contains_itself():
    loop = []
    loop.append(loop)
    message = rejection(make_file(make_rule(value=loop)))
    assert "nested" in message, message


def test_a_value_nested_100_deep_is_still_fine():
    assert Rules(make_file(make_rule(value=nested_list(100)))).get("x.y") == nested_list(100)


# ---- curve-shaped values ------------------------------------------------------------
#
# Any object with both "breaks" and "slopes" is a piecewise-linear curve: one more slope than
# breaks, breaks strictly increasing, every slope finite.


def curve(breaks, slopes):
    return {"breaks": breaks, "slopes": slopes}


GOOD_CURVES = [
    pytest.param(curve([255, 510], [1, 0.5, 0]), id="two-breaks"),
    pytest.param(curve([], [2]), id="no-break-one-slope"),
    pytest.param(curve([0.5, 1.5, 2.5], [0, 1, 2, 3]), id="float-breaks"),
    pytest.param(curve([-5, 0, 5], [1, 1, 1, 1]), id="negative-breaks"),
    pytest.param(curve([100, 200, 255, 510], [1, 2.5, 1.25, 0.625, 0]), id="four-breaks"),
    pytest.param({**curve([1], [1, 0]), "note": "other keys are not checked"}, id="extra-key"),
]

BAD_CURVES = [
    pytest.param(curve([1, 2], [1, 2]), ["slopes", "breaks"], id="too-few-slopes"),
    pytest.param(curve([1], [1, 2, 3]), ["slopes", "breaks"], id="too-many-slopes"),
    pytest.param(curve([], []), ["slopes", "breaks"], id="no-slope-at-all"),
    pytest.param(curve([255, 255], [1, 2, 3]), ["breaks", "increasing"], id="equal-breaks"),
    pytest.param(curve([510, 255], [1, 2, 3]), ["breaks", "increasing"], id="descending-breaks"),
    pytest.param(curve([1, 3, 2], [1, 2, 3, 4]), ["breaks", "increasing"], id="unsorted-breaks"),
    pytest.param(curve([1, 1.0], [1, 2, 3]), ["breaks", "increasing"], id="equal-int-and-float-breaks"),
    pytest.param(curve([1, 2], [1, float("nan"), 0]), ["slopes", "finite"], id="nan-slope"),
    pytest.param(curve([1, 2], [1, float("inf"), 0]), ["slopes", "finite"], id="infinite-slope"),
    pytest.param(curve([1, 2], [-float("inf"), 1, 0]), ["slopes", "finite"], id="minus-infinite-slope"),
    pytest.param(curve([1, float("nan")], [1, 2, 3]), ["breaks", "finite"], id="nan-break"),
    pytest.param(curve([1, 2], [1, "2", 0]), ["slopes[1]", "number"], id="slope-is-a-string"),
    pytest.param(curve([1, 2], [1, None, 0]), ["slopes[1]", "number"], id="slope-is-null"),
    pytest.param(curve([1, 2], [1, True, 0]), ["slopes[1]", "number"], id="slope-is-a-bool"),
    pytest.param(curve(["a", "b"], [1, 2, 3]), ["breaks[0]", "number"], id="break-is-a-string"),
    pytest.param(curve([1, None], [1, 2, 3]), ["breaks[1]", "number"], id="break-is-null"),
    pytest.param(curve(5, [1, 2]), ["breaks", "list"], id="breaks-not-a-list"),
    pytest.param(curve(None, [1]), ["breaks", "list"], id="breaks-null"),
    pytest.param(curve({"1": 2}, [1, 2]), ["breaks", "list"], id="breaks-an-object"),
    pytest.param(curve([1], "ab"), ["slopes", "list"], id="slopes-not-a-list"),
]

# A few defects, tried in every place a curve can sit.
CURVES_TRIED_EVERYWHERE = [
    curve([1, 2], [1, 2]),
    curve([1, 3, 2], [1, 2, 3, 4]),
    curve([1, 2], [1, float("nan"), 0]),
]


@pytest.mark.parametrize("good", GOOD_CURVES)
def test_a_well_formed_curve_is_accepted(good):
    assert Rules(make_file(make_rule(value=good))).get("x.y") == good


@pytest.mark.parametrize("place", PLACES)
def test_a_well_formed_curve_is_accepted_wherever_it_sits(place):
    Rules(make_file(make_rule(**PLACES[place](curve([255, 510], [1, 0.5, 0])))))


@pytest.mark.parametrize(("bad", "fragments"), BAD_CURVES)
def test_a_malformed_curve_is_rejected_with_a_clear_message(bad, fragments):
    message = rejection(make_file(make_rule(value=bad)))
    assert "x.y" in message and "value" in message, message
    for fragment in fragments:
        assert fragment in message, message


@pytest.mark.parametrize("place", PLACES)
def test_a_malformed_curve_is_rejected_wherever_it_sits(place):
    for bad in CURVES_TRIED_EVERYWHERE:
        message = rejection(make_file(make_rule(**PLACES[place](bad))))
        assert "x.y" in message, message


def test_a_malformed_curve_in_a_file_is_rejected_by_the_loader(tmp_path):
    for literal, fragment in (
        ('{"breaks": [2, 1], "slopes": [1, 2, 3]}', "increasing"),
        ('{"breaks": [1, 2], "slopes": [1, 1e999, 0]}', "finite"),
    ):
        with pytest.raises(RulesError, match=fragment):
            load(write(tmp_path, text_with(literal, value="@@")))


@pytest.mark.parametrize(
    "partial",
    [{"breaks": [3, 1]}, {"slopes": [1, 2, 3, 4]}, {"break": [3, 1], "slope": []}],
    ids=["only-breaks", "only-slopes", "other-names"],
)
def test_a_value_without_both_breaks_and_slopes_is_not_a_curve(partial):
    assert Rules(make_file(make_rule(value=partial))).get("x.y") == partial


def curves_in(node, where):
    """Every object with both 'breaks' and 'slopes' inside a JSON value, with where it was found."""
    found = []
    if isinstance(node, dict):
        if "breaks" in node and "slopes" in node:
            found.append((where, node))
        for key, child in node.items():
            found.extend(curves_in(child, f"{where}.{key}"))
    elif isinstance(node, list):
        for number, child in enumerate(node):
            found.extend(curves_in(child, f"{where}[{number}]"))
    return found


def test_every_curve_of_the_real_file_is_well_formed(raw):
    # Judged here, with its own small walk, and not by the loader that the other tests check.
    found = []
    for rule in raw["rules"]:
        places = [("value", rule["value"])]
        places += [(f"levels.{key}", value) for key, value in rule.get("levels", {}).items()]
        places += [(f"alternatives[{n}].value", alt["value"]) for n, alt in enumerate(rule.get("alternatives", []))]
        for where, value in places:
            found.extend((rule["id"], path, found_curve) for path, found_curve in curves_in(value, where))
    assert {rule_id for rule_id, _, _ in found} >= {"hp.sta_curve", "mana.wis_bands"}
    for rule_id, path, found_curve in found:
        breaks, slopes = found_curve["breaks"], found_curve["slopes"]
        assert len(slopes) == len(breaks) + 1, (rule_id, path)
        assert all(a < b for a, b in zip(breaks, breaks[1:], strict=False)), (rule_id, path)
        assert all(math.isfinite(slope) for slope in slopes), (rule_id, path)


# ---- the public files cite no private document --------------------------------------

# Words that cite a document outside this repository: a numbered work item, a roadmap, a lettered
# attachment, a numbered stage, a section sign. Built from pieces so that this file does not
# match itself.
PRIVATE_DOCUMENT_WORDS = re.compile(
    "|".join(
        r"\b" + head + tail
        for head, tail in (
            ("Ta", r"sk\s*[0-9]"),
            ("pl", r"an\b"),
            ("Appen", r"dix\s+[A-Z]\b"),
            ("Pha", r"se\s*[0-9]"),
        )
    )
    + "|" + chr(0xA7),  # a section sign
    re.IGNORECASE,
)


def test_the_rules_files_cite_no_private_planning_document():
    hits = []
    for path in (RULES_PATH, SCHEMA_PATH, Path(rules_module.__file__), Path(__file__)):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            hits.extend(f"{path.name}:{number}: {found.group()!r}" for found in PRIVATE_DOCUMENT_WORDS.finditer(line))
    assert hits == [], "\n".join(hits)
