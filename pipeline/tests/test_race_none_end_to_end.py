"""A page that says ``Race: NONE``, from the statsblock to the solver: no race can wear the item.

The chain is the real one. The page parser and the normalizer give the catalog item (``races`` is ``[]``),
``at_tier`` gives the model's view of it (``races`` is the empty set: no race may wear it, which is not ``None``,
every race), and the MILP builder and the pruner leave the item out for every race of the game. The pages are
invented; the first is shaped like the real page of a warrior's temporary spear whose statsblock ends in
``Class: WAR`` and ``Race: NONE``.
"""

import pytest

from solver_helpers import TABLES
from trioforge import rules as rules_module
from trioforge.data.normalize import normalize, validate_item
from trioforge.model.items import at_tier
from trioforge.model.profile import make_profile
from trioforge.solver.model import BuildOptions, build_milp
from trioforge.solver.prune import prune_report
from trioforge.sources.itempage import ParsedPage, parse_page

RULES = rules_module.load()
RACES = [race["code"] for race in TABLES.races["races"]]
TRIO = ("WAR", "CLR", "ENC")  # the spear below is for warriors


def block(*statsblock_lines):
    return "<br>\n".join(statsblock_lines)


SPEAR = block(
    "MAGIC ITEM  LORE ITEM  TEMPORARY  ", "Slot: PRIMARY SECONDARY", "Skill: Piercing  Atk Delay: 29", "DMG: 6",
    "WT: 7.0  Size: LARGE", "Class: WAR", "Race: NONE",
)  # fmt: skip
RING = block("Slot: FINGER", "STA: +20  HP: +50", "WT: 0.1  Size: TINY", "Class: ALL", "Race: {race}")
GUARD = block("Slot: SECONDARY", "Type: Shield", "AC: 20", "WT: 5.0  Size: MEDIUM", "Class: ALL", "Race: {race}")


def catalog_item(pageid, name, statsblock):
    """The catalog item of an invented page: parsed, normalized and checked against the schema."""
    page = {
        "pageid": pageid,
        "ns": 0,
        "title": name,
        "revid": pageid * 10,
        "content": "{{Itempage\n|itemname = " + name + "\n|statsblock =\n" + statsblock + "\n}}",
    }
    parsed = parse_page(page)
    assert isinstance(parsed, ParsedPage), parsed
    item = normalize(parsed)
    validate_item(item)
    return item


def pool(tier=0):
    """Two items that no race can wear, an item open to every race and an item for humans only."""
    pages = [
        (9101, "Shadowed Zorblax Spear", SPEAR),
        (9102, "Zorblax Ring of Nobody", RING.format(race="NONE")),
        (9103, "Zorblax Ring of Everybody", RING.format(race="ALL")),
        (9104, "Zorblax Ring of Humans", RING.format(race="HUM")),
    ]
    return {name: at_tier(catalog_item(pageid, name, text), tier, RULES) for pageid, name, text in pages}


NOBODY = ("w9101", "w9102")  # the keys of the two items that say Race: NONE


def test_a_page_that_says_race_none_is_an_empty_list_in_the_catalog_and_the_empty_set_in_the_model():
    spear = catalog_item(9101, "Shadowed Zorblax Spear", SPEAR)
    assert spear["races"] == [] and spear["classes"] == ["WAR"] and spear["slots"] == ["PRIMARY", "SECONDARY"]
    assert spear["weapon"] == {"skill": "Piercing", "dmg": 6, "delay": 29, "bonus": None}
    assert [(w["code"], w["field"]) for w in spear["parse_warnings"]] == [("no-classes", "race")]
    for tier in (0, 4, 10):
        vecs = pool(tier)
        assert vecs["Shadowed Zorblax Spear"].races == frozenset() and vecs["Zorblax Ring of Nobody"].races == frozenset()
        assert vecs["Zorblax Ring of Everybody"].races is None  # ALL is every race
        assert vecs["Zorblax Ring of Humans"].races == frozenset({"HUM"})


@pytest.mark.parametrize("options", [BuildOptions(), BuildOptions(any_rule="explicit")], ids=["any-all", "any-explicit"])
def test_no_column_and_no_survivor_exists_for_an_item_that_no_race_can_wear(options):
    vecs = list(pool().values())
    seen_setups = set()
    for race in RACES:
        profile = make_profile(race, TRIO, 50, "tank", None, None, TABLES, items=vecs)
        for setup in profile.setups:
            seen_setups.add(setup)
            keys = {key for _, key in build_milp(profile, vecs, setup, None, options).colmap.values()}
            assert not keys & set(NOBODY), (race, setup)
            assert "w9103" in keys, (race, setup)  # the item for every race has its columns
            assert ("w9104" in keys) == (race == "HUM"), (race, setup)  # and the human item only for humans
            report = prune_report(vecs, profile, 0, setup, None, options)
            assert {key for key, _ in report.dropped} >= set(NOBODY)
            assert report.dropped[("w9101", 0)] == ("race", None) and report.dropped[("w9102", 0)] == ("race", None)
            assert not {item.key for item in report.kept} & set(NOBODY), (race, setup)
    assert seen_setups  # the loops ran


def test_a_shield_that_no_race_can_wear_does_not_make_the_shield_setup():
    nobody = at_tier(catalog_item(9105, "Zorblax Guard of Nobody", GUARD.format(race="NONE")), 0, RULES)
    everybody = at_tier(catalog_item(9106, "Zorblax Guard of Everybody", GUARD.format(race="ALL")), 0, RULES)
    assert nobody.is_shield and nobody.races == frozenset() and everybody.is_shield and everybody.races is None
    for race in RACES:
        without = make_profile(race, TRIO, 50, "tank", None, None, TABLES, items=[nobody])
        with_one = make_profile(race, TRIO, 50, "tank", None, None, TABLES, items=[nobody, everybody])
        assert "1h-shield" not in without.setups, race
        assert "1h-shield" in with_one.setups, race
