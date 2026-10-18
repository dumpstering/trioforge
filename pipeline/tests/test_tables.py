"""Tests for the model's lookup tables: ``trioforge.model.tables.load``.

``load(root)`` reads derived/client/{basedata,acmitigation,skillcaps,zones}.json, rules/races.json and
rules/rules.json under ``root`` and returns one read-only ``Tables``. It fails closed: a damaged table
raises ``TablesError`` listing every problem found, never a half-filled table.
"""

import copy
import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from trioforge import rules as rules_module
from trioforge.model import tables
from trioforge.model.tables import Tables, TablesError, load

REPO = Path(__file__).resolve().parents[2]
CLASS_CODES = "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split()


@pytest.fixture(scope="module")
def real():
    return load()


# ---- the real tables -----------------------------------------------------------------------


def test_the_default_root_is_the_repository(real):
    assert tables.REPO == REPO
    assert isinstance(real, Tables)
    assert load(REPO).softcap == real.softcap
    assert load(str(REPO)).softcap == real.softcap


def test_the_rules_and_the_races_are_the_repository_files(real):
    assert isinstance(real.rules, rules_module.Rules)
    assert real.rules.version == rules_module.load().version
    assert real.rules.get("level.current") == 50
    assert [race["code"] for race in real.races["races"]][:3] == ["HUM", "BAR", "ERU"]
    assert [klass["code"] for klass in real.races["classes"]] == CLASS_CODES


def test_basedata_is_keyed_by_class_code_and_level(real):
    row = real.basedata[("PAL", 50)]
    assert row["hp"] == 1440.0 and row["hp_fac"] == 4.8
    assert row["mana"] == 900.0 and row["mana_fac"] == 4.5
    assert row["end"] == 652.0 and row["end_fac"] == 3.25
    assert {"hp_regen", "end_regen"} <= set(row)
    assert "class" not in row and "level" not in row
    assert real.basedata[("WAR", 50)]["mana"] == 0.0
    assert real.basedata[("BER", 50)]["end_fac"] == 4.25


def test_every_class_has_every_level_from_one_to_sixty(real):
    wanted = {(code, level) for code in CLASS_CODES for level in range(1, 61)}
    assert set(real.basedata) == wanted
    assert set(real.softcap) == wanted


def test_softcap_is_the_cap_and_the_rate_past_it(real):
    assert real.softcap[("PAL", 50)] == (392, 0.33)
    assert real.softcap[("WAR", 50)] == (410, 0.35)
    assert real.softcap[("PAL", 55)] == (402, 0.33)
    assert real.softcap[("WIZ", 50)] == (328, 0.25)


def test_skill_caps_are_keyed_by_class_skill_name_and_level(real):
    assert real.skillcap[("PAL", "Defense", 50)] == 230
    assert real.skillcap[("MNK", "Dual Wield", 50)] == 252
    assert real.skillcap[("WAR", "Dual Wield", 50)] == 210
    assert ("SHD", "Dual Wield", 50) not in real.skillcap  # a class without the skill has no row
    assert all(isinstance(key[1], str) for key in real.skillcap)  # skills the client does not name are left out


def test_zones_are_keyed_by_id(real):
    assert real.zones[1]["name"] == "South Qeynos"
    assert set(real.zones[1]) == {"name", "c3", "c4", "flagged"}
    assert isinstance(real.zones[1]["flagged"], bool)
    assert len(real.zones) > 600


def test_the_tables_are_read_only(real):
    with pytest.raises(TypeError):
        real.basedata[("PAL", 50)]["hp"] = 1
    with pytest.raises(TypeError):
        real.basedata[("PAL", 61)] = {}
    with pytest.raises(TypeError):
        real.softcap[("PAL", 50)] = (1, 1)
    with pytest.raises(TypeError):
        real.skillcap[("PAL", "Defense", 50)] = 1
    with pytest.raises(TypeError):
        real.zones[1]["name"] = "x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        real.rules = None


def test_the_client_pool_numbers_agree_with_the_rules_file(real):
    # rules.json says every mana class has 900 base mana and 4.5 a point at level 50; the client table must say so too.
    base, per_stat = real.rules.get("mana.base_l50"), real.rules.get("mana.per_stat_l50")
    stat_by_class = real.rules.get("mana.stat_by_class")
    mana_classes = set(stat_by_class["WIS"]) | set(stat_by_class["INT"])
    assert len(mana_classes) == 12
    for code in CLASS_CODES:
        row = real.basedata[(code, 50)]
        if code in mana_classes:
            assert (row["mana"], row["mana_fac"]) == (base, per_stat)
        else:
            assert (row["mana"], row["mana_fac"]) == (0.0, 0.0)


def test_the_softcap_of_the_paladin_matches_the_rules_and_the_plan(real):
    # 392 * (100 + 10 + 2) / 100 = 439.04, floored: the softcap of Combat Stability 3 and Physical Enhancement.
    cap, rate = real.softcap[("PAL", 50)]
    cs3 = real.rules.get("ac.softcap.combat_stability_pct")["3"]
    pe = real.rules.get("ac.softcap.physical_enhancement_pct")
    assert (cs3, pe) == (10, 2)
    assert cap * (100 + cs3 + pe) // 100 == 439
    # the rate is the Paladin's own, from the client table; the rule only says where it comes from
    assert rate == 0.33
    assert real.rules.get("ac.softcap.past_cap_rate").startswith("per class from Resources/ACMitigation.txt")


# ---- reading a root that is not the repository ---------------------------------------------

BASEDATA_ROW = {
    "class": 1, "level": 50, "hp": 1500.0, "mana": 0.0, "end": 900.0, "hp_regen": 7.0, "end_regen": 13.0,
    "hp_fac": 5.0, "mana_fac": 0.0, "end_fac": 4.5,
}
AC_ROW = {"class": 1, "level": 50, "ac_cap": 410, "past_cap_rate": 0.35}
SKILL_ROWS = [{"class": 1, "skill": 15, "level": 50, "cap": 230}, {"class": 1, "skill": 9, "level": 50, "cap": 5}]
ZONE_ROW = {"id": 7, "name": "Invented Hollow", "c3": 0, "c4": 2, "flagged": False}
BASEDATA_ROW_WITHOUT_KEYS = {k: v for k, v in BASEDATA_ROW.items() if k not in ("class", "level")}


def synthetic_files():
    return {
        "basedata": {"provenance": {}, "rows": [copy.deepcopy(BASEDATA_ROW)]},
        "acmitigation": {"provenance": {}, "rows": [copy.deepcopy(AC_ROW)]},
        "skillcaps": {"provenance": {}, "skill_names": {"15": "Defense"}, "rows": copy.deepcopy(SKILL_ROWS)},
        "zones": {"provenance": {}, "flagged_count": 0, "zones": [copy.deepcopy(ZONE_ROW)]},
    }


def make_root(tmp_path, files=None, raw=None):
    """A root with the real rules and races and small invented client tables. ``raw`` maps a table name to text."""
    (tmp_path / "rules").mkdir(exist_ok=True)
    (tmp_path / "derived" / "client").mkdir(parents=True, exist_ok=True)
    for name in ("rules.json", "races.json"):
        shutil.copy(REPO / "rules" / name, tmp_path / "rules" / name)
    for name, data in (files or synthetic_files()).items():
        (tmp_path / "derived" / "client" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    for name, text in (raw or {}).items():
        (tmp_path / "derived" / "client" / f"{name}.json").write_text(text, encoding="utf-8")
    return tmp_path


def test_a_small_root_loads(tmp_path):
    small = load(make_root(tmp_path))
    assert small.basedata == {("WAR", 50): BASEDATA_ROW_WITHOUT_KEYS}
    assert small.softcap == {("WAR", 50): (410, 0.35)}
    assert small.skillcap == {("WAR", "Defense", 50): 230}
    assert small.zones == {7: {"name": "Invented Hollow", "c3": 0, "c4": 2, "flagged": False}}



def broken(table, mutate):
    files = synthetic_files()
    mutate(files[table])
    return files


CORRUPTIONS = {
    "duplicate basedata row": (
        lambda: broken("basedata", lambda t: t["rows"].append(copy.deepcopy(BASEDATA_ROW))), "duplicate"),
    "class above sixteen": (lambda: broken("basedata", lambda t: t["rows"][0].update({"class": 17})), "class"),
    "class zero": (lambda: broken("basedata", lambda t: t["rows"][0].update({"class": 0})), "class"),
    "level zero": (lambda: broken("basedata", lambda t: t["rows"][0].update({"level": 0})), "level"),
    "missing factor": (lambda: broken("basedata", lambda t: t["rows"][0].pop("hp_fac")), "hp_fac"),
    "extra column": (lambda: broken("basedata", lambda t: t["rows"][0].update({"mystery": 1})), "mystery"),
    "negative number": (lambda: broken("basedata", lambda t: t["rows"][0].update({"hp": -1.0})), "hp"),
    "text for a number": (lambda: broken("basedata", lambda t: t["rows"][0].update({"end": "900"})), "end"),
    "boolean for a number": (lambda: broken("basedata", lambda t: t["rows"][0].update({"level": True})), "level"),
    "rate above one": (
        lambda: broken("acmitigation", lambda t: t["rows"][0].update({"past_cap_rate": 1.5})), "past_cap_rate"),
    "cap of zero": (lambda: broken("acmitigation", lambda t: t["rows"][0].update({"ac_cap": 0})), "ac_cap"),
    "duplicate softcap row": (
        lambda: broken("acmitigation", lambda t: t["rows"].append(copy.deepcopy(AC_ROW))), "duplicate"),
    "duplicate skill row": (
        lambda: broken("skillcaps", lambda t: t["rows"].append(copy.deepcopy(SKILL_ROWS[0]))), "duplicate"),
    "negative skill cap": (lambda: broken("skillcaps", lambda t: t["rows"][0].update({"cap": -1})), "cap"),
    "no skill names": (lambda: broken("skillcaps", lambda t: t.pop("skill_names")), "skill_names"),
    "duplicate zone": (lambda: broken("zones", lambda t: t["zones"].append(copy.deepcopy(ZONE_ROW))), "duplicate"),
    "blank zone name": (lambda: broken("zones", lambda t: t["zones"][0].update({"name": " "})), "name"),
    "no rows": (lambda: broken("basedata", lambda t: t.update({"rows": []})), "no rows"),
    "rows is not a list": (lambda: broken("basedata", lambda t: t.update({"rows": {}})), "rows"),
}


@pytest.mark.parametrize("name", sorted(CORRUPTIONS))
def test_a_damaged_table_is_refused_and_named(tmp_path, name):
    make_files, fragment = CORRUPTIONS[name]
    with pytest.raises(TablesError) as caught:
        load(make_root(tmp_path, make_files()))
    assert fragment in str(caught.value)
    assert caught.value.problems


def test_every_problem_is_reported_not_only_the_first(tmp_path):
    files = synthetic_files()
    files["basedata"]["rows"][0]["class"] = 99
    files["acmitigation"]["rows"][0]["past_cap_rate"] = -1
    files["zones"]["zones"][0]["name"] = ""
    with pytest.raises(TablesError) as caught:
        load(make_root(tmp_path, files))
    text = str(caught.value)
    assert "basedata" in text and "acmitigation" in text and "zones" in text
    assert len(caught.value.problems) >= 3


def test_text_that_is_not_json_is_refused(tmp_path):
    with pytest.raises(TablesError, match="not valid JSON"):
        load(make_root(tmp_path, raw={"basedata": "{ not json"}))


def test_a_missing_table_is_refused_by_name(tmp_path):
    root = make_root(tmp_path)
    (root / "derived" / "client" / "skillcaps.json").unlink()
    with pytest.raises(TablesError, match="skillcaps.json"):
        load(root)


def test_a_root_without_any_tables_is_refused(tmp_path):
    with pytest.raises(TablesError):
        load(tmp_path / "nowhere")


def test_a_damaged_rules_file_is_still_refused_by_the_rules_loader(tmp_path):
    root = make_root(tmp_path)
    (root / "rules" / "rules.json").write_text("{}", encoding="utf-8")
    with pytest.raises(rules_module.RulesError):
        load(root)
