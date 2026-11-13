"""The picture of an item on the pages and in the data files: the same item gets the same picture on a trio page, on its own page, in a shard and in the list the browser reads.

The rule is ``itemicon.icon_name`` (tried in ``test_site_itemicon.py``); here it is held to what the site does with it, and the build is held to its one gate: it makes pictures only from the catalog
the results were made from, and it says so with an error when it has none. The tests that build the site need Node and ``npm ci`` (esbuild) and skip without them, like the other tests of the build.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from site_helpers import parse
from test_art_sheet import REDRAWN, pixel_digest
from test_site_build import MANIFEST, make_changelog, need_node, run_build

from trioforge.export import browser
from trioforge.site import art, build, data, view

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "fixtures" / "site" / "results"
ART = REPO / "pipeline" / "trioforge" / "site" / "static" / "art"


def table() -> dict:
    return json.loads((RESULTS / "items.json").read_text(encoding="utf-8"))


def records() -> dict[str, dict]:
    return {browser.record_key(record): record for record in table()["items"]}


def own_icons() -> dict[str, str]:
    """What the build gives the fixture's items when it is told to build without the catalog: the rule on each record of the table, which has no category and no instrument."""
    return {key: icon for key, record in records().items() if (icon := art.own_icon(record)) is not None}


def row_pictures() -> dict[str, str]:
    """What the shards' ``ic`` and the list say of each item of the fixture: its own picture, else the pouch if it fits a held place, else what its page heading shows (none where the places it fits have
    several pictures): the picture an item has where the place it stands in does not decide, as an any row does not."""
    return {key: icon for key, record in records().items() if (icon := art.item_picture(art.own_icon(record), record["slots"])) is not None}


PLACES = tuple(art.fallback_icon(group) for group in data.SLOT_INSTANCES)  # (a worn place's own picture; a held place the pouch, which a filled row with no picture of its own shows; an any row none: its item decides)


def icons_of_the_fixture() -> data.ItemIcons:
    return build.item_icons(table(), {})


def name_of(names: list[str], char: str) -> str | None:
    return None if char == "-" else names[data.ICON_DIGITS.index(char)]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("site-icons")
    out = tmp / "dist"
    run_build(out, tmp)
    return out


def _scenario():
    trio = data.load_trio(RESULTS / "pal-mnk-ber")
    return next(iter(trio.shards.values())).scenarios[0]


# ---- the codes of a data file -------------------------------------------------------------------------------------------------------------------


def test_icon_names_are_told_by_one_character_each_in_the_order_they_are_first_used():
    names, codes = data.icon_table(["icon-sword-1h", None, "icon-helm", "icon-sword-1h", None, "icon-shield"])
    assert names == ["icon-sword-1h", "icon-helm", "icon-shield"]
    assert codes == "0-10-2"
    assert data.icon_table([]) == ([], "")
    assert data.icon_table([None, None]) == ([], "--")


def test_a_data_file_can_name_as_many_icons_as_it_has_characters_and_no_more():
    room = len(data.ICON_DIGITS)
    many = [f"icon-n{n}" for n in range(room)]
    names, codes = data.icon_table(many)
    assert names == many and len(set(codes)) == room and "-" not in codes
    with pytest.raises(ValueError, match=str(room)):
        data.icon_table([*many, "icon-one-too-many"])


def test_the_characters_of_a_data_file_have_room_for_every_picture_the_site_can_name_in_one_file_and_are_plain():
    """The thirteen pictures of the held things and the pouch took the names of the list of the item table past the 62 characters a digit, a small letter and a capital make: the alphabet got more
    characters, all plain ASCII that a JSON string keeps as it is (one byte each, no escape) and none of them the dash that says no picture. The browser's copy is the same string. The letters are the
    consonants only (no vowel, no y, in both cases), so that a string of codes cannot spell a word: the privacy scan of a built site flagged a run of letters of an `ic` string that did."""
    from trioforge.site import itemicon

    digits = data.ICON_DIGITS
    assert digits.startswith("0123456789")  # (the ten digits first: the codes of the first ten pictures are the digits they always were)
    assert not set(digits) & set("aeiouyAEIOUY"), digits  # (no vowel and no y, in either case: a string of codes cannot spell a word)
    assert {c for c in digits if c.isalpha()} == set("bcdfghjklmnpqrstvwxz" + "BCDFGHJKLMNPQRSTVWXZ")  # (every other letter is there)
    assert len(set(digits)) == len(digits) and data.NO_ICON_DIGIT == "-" and "-" not in digits
    assert all(32 < ord(char) < 127 and char not in '"\\<>&\'' for char in digits), digits  # (no character a JSON string, a page or a quote would change)
    assert json.dumps(digits) == '"' + digits + '"'
    assert not set(digits) & set(":/\\"), digits  # (a string of these characters could read as a path to the release scan: a drive, a share, a folder; the review took the colon and the slash out)
    assert len(digits) == 10 + 20 + 20 + 22 + 1  # (digits, the consonants in two cases, 22 punctuation characters and the backtick)
    assert "`" in digits  # (the backtick is plain ASCII: a JSON string keeps it, a JS string in double quotes keeps it, the regular expression that reads shard.js for the tests takes it)
    everything = set(itemicon.ALL_ICONS) | set(art.SLOT_ICONS.values()) | {art.HELD_ICON}
    assert len(everything) <= len(digits) - 4, f"{len(everything)} names for {len(digits)} characters: the list of the item table names them all, and the next pictures need room (the build stops with one line when a file names more)"
    script = (REPO / "pipeline" / "trioforge" / "site" / "static" / "shard.js").read_text(encoding="utf-8")
    assert f'const ICON_DIGITS = "{digits}";' in script  # (the browser reads with the string the generator writes with)
    assert re.fullmatch(r'const ICON_DIGITS = "[^"]+";', f'const ICON_DIGITS = "{digits}";')  # (and the tests of the page read it with this expression: nothing in the string ends it early)


@pytest.mark.parametrize("bad", ["helm", "icon-", "icon-Helm", "icon-a b", 'icon-x"><img>', "icon-a_b", "icon--a", "icon-a-", "icon-é", "x" * 60, "icon-" + "a" * 60, 7, None])
def test_a_name_the_browser_would_refuse_is_refused_here_first(bad):
    with pytest.raises(ValueError, match="icon"):
        data.check_icon_names([bad])
    data.check_icon_names(["icon-helm", "icon-sword-1h", "icon-hammer-2h"])  # (the names of the art are fine)


# ---- the rows of the trio page --------------------------------------------------------------------------------------------------------------------


HELD = ("PRIMARY", "SECONDARY", "RANGE", "ANY")  # the places that hold something in a hand, at range or anywhere: the item's own picture only
HELD_ROWS = {"PRIMARY": "Main hand", "SECONDARY": "Off hand", "RANGE": "Range", "ANY": "Any slot 1"}


def _part(icon):
    """The part of the body a picture of armor or of a place of armor is of (``icon-chest-plate``, ``icon-chest``, ``icon-hands-leather``: its part), or None."""
    found = re.fullmatch(r"icon-(helm|chest|arms|legs|feet|hands)(?:-(?:cloth|leather|chain|plate))?", icon or "")
    return found.group(1) if found else None


#: the thirteen pictures of the held things and the pouch: they stay on a held row (the heading of the page of an item has them too)
HELD_PICTURES = {f"icon-{name}" for name in "idol stone horn lantern cup scroll rod whip claw pick polearm charm fishing-pole pouch".split()}


def heading(slots):
    """The picture of the page heading of an item that has none of its own, written plainly: the place's picture when every place it fits is worn and they all have the one picture, none otherwise; the
    pouch for an item that fits held places only."""
    if slots and all(slot in ("PRIMARY", "SECONDARY", "RANGE") for slot in slots):
        return "icon-pouch"
    pictures = {art.SLOT_ICONS.get(slot) for slot in slots}
    return next(iter(pictures)) if len(pictures) == 1 and None not in pictures else None


def row_picture(own, group, filled=True, slots=()):
    """The picture of a row of the kit, written out plainly (the code says it once, in ``art.row_icon``; this is the rule it is held to): in a worn place the item's own picture, else the place's,
    always (the other places the item fits do not matter), except that a picture of the held things stays on a held row and a picture of armor stays in the place of its own part; in the main hand, the off
    hand and the range the item's own, else the pouch; in an any row the item's own, else the pouch if it fits a held place, else what its page heading shows (the any row takes whatever fits, so the
    item's own places say what it is)."""
    place = art.slot_icon(group)
    if not filled:
        return place  # (an empty row: its place's picture, none in a held place)
    if group == "ANY":
        if own is not None:
            return own
        return "icon-pouch" if {"PRIMARY", "SECONDARY", "RANGE"} & set(slots) else heading(slots)
    if group in HELD:
        return own if own is not None else "icon-pouch"  # (the pouch: the fallback of a filled held row)
    if own is None or own in HELD_PICTURES:
        return place
    return place if _part(own) is not None and _part(own) != _part(place) else own


def browser_row(ic, places, index, filled):
    """The rule of ``static/trio.js`` rowIcon, written plainly: what the page code draws for the item with this ``ic`` in the place at this index, given the file's ``pl`` (names or None)."""
    place = places[index]
    if index >= 17:  # the held places are the last five of the 22
        return None if not filled else (ic if ic is not None else place)
    if not filled:
        return place
    if place is None:
        return ic
    if ic is None or ic in HELD_PICTURES:
        return place
    return place if _part(ic) is not None and _part(ic) != _part(place) else ic


def _item(key: str, slots: tuple[str, ...]):
    base = next(i for i in _scenario().kit if i)
    return dataclasses.replace(base, key=key, name=f"Item {key}", slots=slots)


def _rows_with(item, group: str, icons: dict[str, str]):
    kit = tuple(item if g == group else None for g in data.SLOT_INSTANCES)
    return {row.slot: row.icon for row in view.kit_rows(dataclasses.replace(_scenario(), kit=kit), icons=icons)}


def test_a_row_of_the_kit_has_the_picture_of_its_item_in_a_held_place_and_else_that_of_its_place_in_a_worn_one():
    scenario = _scenario()
    chest = data.SLOT_INSTANCES.index("CHEST")
    icons = {**own_icons(), scenario.kit[chest].key: "icon-chest-plate"}  # (the fixture's items have no armor picture without a catalog: this one has)
    rows = view.kit_rows(scenario, icons=icons)
    seen = set()
    for row, group, item in zip(rows, data.SLOT_INSTANCES, scenario.kit, strict=True):
        own = icons.get(item.key) if item is not None else None
        assert row.icon == row_picture(own, group, item is not None, item.slots if item else ()), (row.slot, item and item.name)
        seen.add(("held" if group in HELD else "worn", "own" if own else "place" if row.icon else "none"))
        assert item is None or row.icon is not None, (row.slot, item.name)  # (no filled row is without a picture)
    assert {("worn", "own"), ("worn", "place"), ("held", "own")} <= seen  # (the fixture's kit has all three)
    without = view.kit_rows(scenario)
    assert [row.icon for row in without] == [
        (art.item_picture(None, item.slots) if group == "ANY" else art.fallback_icon(group)) if item is not None else art.slot_icon(group) for group, item in zip(data.SLOT_INSTANCES, scenario.kit, strict=True)
    ]  # no pictures of items given: the places' own, the pouch in a held place that has an item (in an any row what the item is by its places), none in an empty one


def test_an_empty_place_has_the_picture_of_its_place_and_a_held_one_has_none():
    scenario = _scenario()
    emptied = dataclasses.replace(scenario, kit=tuple(None for _ in scenario.kit))
    rows = view.kit_rows(emptied, icons=own_icons())
    assert [row.icon for row in rows] == [art.slot_icon(group) for group in data.SLOT_INSTANCES]  # (an empty row is unchanged: the pouch is the picture of a filled row)
    assert [row.icon for row, group in zip(rows, data.SLOT_INSTANCES, strict=True) if group in HELD] == [None] * 5  # (the main hand, the off hand, the range and the two any slots)
    assert all(row.icon is not None for row, group in zip(rows, data.SLOT_INSTANCES, strict=True) if group not in HELD)


def test_a_worn_place_has_its_picture_for_an_item_that_fits_other_places_too_as_the_back_straps_of_the_wrist_do():
    """The reviewer's screenshot: Back Straps of Mastery fits the back and the wrist and has no picture of its own; the wrist row had none. The places an item fits do not matter."""
    straps = _item("w1", ("BACK", "WRIST"))
    wrist = _rows_with(straps, "WRIST", {})
    assert wrist["Wrist 1"] == wrist["Wrist 2"] == "icon-wrist"
    assert _rows_with(straps, "BACK", {})["Back"] == "icon-back"
    assert _rows_with(_item("w2", ("EAR", "FINGER")), "EAR", {})["Ear 1"] == "icon-ear" and _rows_with(_item("w2", ("EAR", "FINGER")), "FINGER", {})["Finger 1"] == "icon-ring"
    assert _rows_with(_item("w3", ("CHEST", "AMMO")), "CHEST", {})["Chest"] == "icon-chest"  # (a place the art has no picture of changes nothing)
    assert _rows_with(_item("w4", ("HEAD", "FACE", "NECK")), "FACE", {})["Face"] == "icon-face"


def test_a_held_place_has_the_picture_of_its_item_and_never_one_that_stands_in_for_it():
    """The reviewer's second screenshot: the Soldier's Brooch of the Virtuous, in the range place, was shown a bow. A thing that is no weapon is shown nothing in the main hand, the off hand, the range
    and the any slots (no sword, no bow), and a thing that has a picture of its own is shown it."""
    for group, label in HELD_ROWS.items():
        assert art.slot_icon(group) is None, group
        slots = ("PRIMARY", "SECONDARY") if group == "ANY" else (group,)  # (an any row takes whatever fits: an item that fits a held place)
        assert _rows_with(_item("w5", slots), group, {})[label] == "icon-pouch", group  # (the pouch: the fallback of a filled held row; neither a sword nor a bow)
        assert _rows_with(_item("w5", ("PRIMARY", "SECONDARY", "RANGE", "ANY")), group, {})[label] == "icon-pouch", group
        assert _rows_with(_item("w5", slots), group, {"w5": "icon-wand"})[label] == "icon-wand", group  # (its own: wherever it stands)
    brooch = _item("w6", ("RANGE",))
    assert _rows_with(brooch, "RANGE", {})["Range"] == "icon-pouch"
    assert art.item_icon(brooch.slots) == "icon-pouch"  # (and its page: the pouch, for an item that fits held places only)


def test_an_archery_weapon_is_shown_the_bow_in_the_range_place_by_its_own_picture():
    recurve = {"name": "Hunter's Recurve", "slots": ["RANGE", "AMMO"], "weapon": {"skill": "Archery", "dmg": 10, "delay": 30, "bonus": None}}
    assert art.own_icon(recurve) == "icon-bow"
    assert _rows_with(_item("w7", ("RANGE",)), "RANGE", {"w7": art.own_icon(recurve)})["Range"] == "icon-bow"
    assert _rows_with(_item("w7", ("RANGE",)), "RANGE", {})["Range"] == "icon-pouch"  # (no bow where the item is not an archery weapon: the bow is the picture of one)


def test_a_picture_of_armor_is_shown_only_in_the_place_of_its_own_part():
    """A chest picture never stands on a legs row (nor a legs picture on the chest's): an item whose own picture is a part of armor and that fits another worn place too is shown the place's there."""
    plate = _item("w8", ("CHEST", "WAIST"))
    assert _rows_with(plate, "CHEST", {"w8": "icon-chest-plate"})["Chest"] == "icon-chest-plate"
    assert _rows_with(plate, "WAIST", {"w8": "icon-chest-plate"})["Waist"] == "icon-waist"
    legs = _item("w9", ("LEGS", "CHEST"))
    assert _rows_with(legs, "LEGS", {"w9": "icon-chest-plate"})["Legs"] == "icon-legs"
    assert _rows_with(legs, "CHEST", {"w9": "icon-legs-leather"})["Chest"] == "icon-chest"
    for group in data.SLOT_INSTANCES:  # every picture of armor on every row: its own part's place keeps it, any other has the place's own (or none)
        for own in sorted(itemicon_armor_pictures()):
            row = view.kit_rows(dataclasses.replace(_scenario(), kit=tuple(_item("x", (group,)) if g == group else None for g in data.SLOT_INSTANCES)), icons={"x": own})
            shown = {r.icon for r, g in zip(row, data.SLOT_INSTANCES, strict=True) if g == group}
            assert shown == {row_picture(own, group, True, (group,))}, (own, group)
            if group not in HELD:
                (picture,) = shown
                assert picture in (art.slot_icon(group), own) and (picture != own or _part(own) == _part(art.slot_icon(group))), (own, group)


def itemicon_armor_pictures() -> set[str]:
    from trioforge.site import itemicon

    return {icon for icon in itemicon.ALL_ICONS if _part(icon) is not None and icon.count("-") == 2}


def test_the_page_of_an_item_has_its_own_picture_and_else_the_places_when_every_place_it_fits_is_a_worn_one_of_one_picture():
    assert art.item_icon(["WRIST"]) == "icon-wrist" and art.item_icon(["WRIST", "WRIST"]) == "icon-wrist"
    assert art.item_icon(["BACK", "WRIST"]) is None  # two worn places, two pictures
    for held in (["PRIMARY"], ["SECONDARY"], ["RANGE"], ["PRIMARY", "SECONDARY"]):
        assert art.item_icon(held) == "icon-pouch", held  # (an item that fits held places only has the pouch, as a filled held row has it)
    for other in (["ANY"], ["RANGE", "AMMO"], ["CHEST", "PRIMARY"], ["WRIST", "PRIMARY", "SECONDARY"]):
        assert art.item_icon(other) is None, other  # (an item of both places keeps the answer it had: no picture is claimed for it)
    assert art.item_icon([]) is None


# ---- the shards and the list of the browser -----------------------------------------------------------------------------------------------------


def _credit():
    return build.credit_of(data.load_trio(RESULTS / "pal-mnk-ber").meta)


def _shard_of(extra):
    """A shard of the fixture with one more item in the first kit (for the data a shard writes about an item that the fixture has none like)."""
    shard = next(iter(data.load_trio(RESULTS / "pal-mnk-ber").shards.values()))
    first = shard.scenarios[0]
    kit = list(first.kit)
    kit[0] = extra
    return dataclasses.replace(shard, scenarios=(dataclasses.replace(first, kit=tuple(kit)), *shard.scenarios[1:]))


def test_a_shard_names_the_icons_its_items_use_one_character_for_each_item_and_one_for_each_place():
    trio = data.load_trio(RESULTS / "pal-mnk-ber")
    shard = next(iter(trio.shards.values()))
    credit = build.credit_of(trio.meta)
    icons = icons_of_the_fixture()
    document = json.loads(data.site_shard_json(shard, credit, None, icons))
    names, codes, places = document["icons"], document["ic"], document["pl"]
    assert len(codes) == len(document["items"]) and len(places) == 22 and "sl" not in document  # (a row needs the item's own picture and the place: no more)
    for row, code in zip(document["items"], codes):
        assert name_of(names, code) == row_pictures().get(row[0]), row[0]
    assert [name_of(names, code) for code in places] == list(PLACES)
    assert all(name_of(names, code) == "icon-pouch" for code, group in zip(places, data.SLOT_INSTANCES, strict=True) if group in HELD and group != "ANY")  # (no sword and no bow stands for a thing in a held place: the pouch does)
    assert all(name_of(names, code) is None for code, group in zip(places, data.SLOT_INSTANCES, strict=True) if group == "ANY")  # (an any row: what the item is decides, and that is in ic)
    assert len(names) == len(set(names)) and all(re.fullmatch(r"icon-[a-z0-9]+(?:-[a-z0-9]+)*", name) for name in names)
    plain = json.loads(data.site_shard_json(shard, credit))
    assert "icons" not in plain and "ic" not in plain and "sl" not in plain and "pl" not in plain  # (a shard made without the pictures is what it was)
    assert {k: v for k, v in document.items() if k not in ("icons", "ic", "pl")} == plain


def test_the_list_of_icons_of_the_item_table_has_one_character_for_each_item_in_the_order_of_the_table_and_the_checksum_of_its_file():
    items = data.load_items(RESULTS, [data.load_trio(RESULTS / "pal-mnk-ber")])
    trio = data.load_trio(RESULTS / "pal-mnk-ber")
    document = json.loads(data.site_icons_json(items, icons_of_the_fixture(), build.credit_of(trio.meta)))
    assert document["items"] == hashlib.sha256(items.raw).hexdigest()
    names = document["icons"]
    assert len(document["ic"]) == len(items.document["items"]) and "sl" not in document
    for record, code in zip(items.document["items"], document["ic"], strict=True):
        assert name_of(names, code) == row_pictures().get(browser.record_key(record)), record["name"]
    assert [name_of(names, code) for code in document["pl"]] == list(PLACES)
    assert document["v"] == 1 and document["release"] == trio.meta.data_tag


# ---- the catalog the pictures of the armor come from: the one gate ----------------------------------------------------------------------------------


def _catalog_for(tmp_path: Path, items: dict, categories: dict[str, list[str]] | None = None, mods: dict[str, dict] | None = None) -> tuple[Path, dict]:
    """A small catalog in the shape of the real one (the fixture's invented items, with the categories and the instrument modifiers a test gives them by name), and the item table with the
    fingerprint that says it was made from that file."""
    categories, mods = categories or {}, mods or {}
    catalog = {"version": "x", "items": [{"key": browser.record_key(r), "name": r["name"], "categories": categories.get(r["name"], []), "instrument_mods": mods.get(r["name"], {})} for r in items["items"]]}
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    stamped = dict(items)
    stamped["inputs"] = browser.inputs_fingerprint(hashlib.sha256(path.read_bytes()).hexdigest(), stamped)
    return path, stamped


#: the fixture's armor, in the fashion category a test says it has: what the pictures of the built pages and shards are held to
ARMOR = {
    "Saltmarsh Jerkin": ["Fashion: Leather"],
    "Breastplate of Warding": ["Fashion: Plate"],
    "Gauntlets of Endless Wrath": ["Fashion: Plate"],
    "Helm of the Stoneward": ["Fashion: Plate"],
    "Greaves of the Stoneward": ["Fashion: Plate"],
    "Boots of the Wayfarer": ["Fashion: Leather"],
    "Crown of the Vanguard": ["Fashion: Cloth"],  # a crown is not the hood of the cloth head: the picture of the place
}
MODS = {"Tinker's Awl": {"Brass": 12}}  # (an invented catalog that says an awl has the modifiers of an instrument: the test is of the data on its way to a page, not of the awl)


def test_the_catalog_the_results_were_made_from_gives_the_categories_of_the_armor(tmp_path):
    path, stamped = _catalog_for(tmp_path, table(), ARMOR, MODS)
    extras = build.load_icon_extras(stamped, path)
    assert set(extras) == set(records())
    chest = next(r for r in stamped["items"] if r["name"] == "Breastplate of Warding")
    assert art.own_icon({**chest, **extras[browser.record_key(chest)]}) == "icon-chest-plate"
    assert extras[browser.record_key(chest)]["categories"] == ["Fashion: Plate"]
    awl = next(r for r in stamped["items"] if r["name"] == "Tinker's Awl")
    assert extras[browser.record_key(awl)]["instrument_mods"] == {"Brass": 12}


def test_a_catalog_that_is_not_the_one_the_results_were_made_from_or_is_not_there_is_an_error_never_a_quiet_loss_of_the_pictures(tmp_path):
    path, stamped = _catalog_for(tmp_path, table(), ARMOR)
    build.load_icon_extras(stamped, path)  # (the right one)
    with pytest.raises(build.BuildError, match="not the one the results were made from"):
        build.load_icon_extras({**stamped, "inputs": "0" * 64}, path)  # the table says another
    path.write_bytes(path.read_bytes() + b" ")  # one more byte in the catalog
    with pytest.raises(build.BuildError, match="not the one the results were made from"):
        build.load_icon_extras(stamped, path)
    with pytest.raises(build.BuildError, match="gone.json"):
        build.load_icon_extras(stamped, tmp_path / "gone.json")


def test_the_catalog_of_the_repository_is_the_one_the_newest_release_was_made_from():
    """The release's own pointer (releases/<release>.json) records the SHA-256 of the catalog the release was made from; the file the build reads by default is that catalog, so a table of
    the real release has the fingerprint made of its hash. The real results are not in the repository: this is what can be held here."""
    assert build.DEFAULT_CATALOG == REPO / "derived" / "catalog.json"
    newest = max((REPO / "releases").glob("data-*.json"))
    pointer = json.loads(newest.read_text(encoding="utf-8"))
    assert hashlib.sha256(build.DEFAULT_CATALOG.read_bytes()).hexdigest() == pointer["catalog_sha256"], f"derived/catalog.json is not the catalog {newest.name} says it was made from"
    items = json.loads(build.DEFAULT_CATALOG.read_bytes())["items"]
    assert items and all("categories" in item and "instrument_mods" in item for item in items[:2000])


def test_the_build_checks_the_names_it_writes_against_the_pattern_of_the_browser_and_the_number_of_the_characters():
    fine = data.ItemIcons({"w1": "icon-axe-1h", "w2": "icon-ear"}, PLACES)
    build.check_icons(fine)
    with pytest.raises(build.BuildError, match="icon"):
        build.check_icons(data.ItemIcons({"w1": "icon-Axe"}, PLACES))
    with pytest.raises(build.BuildError, match="icon"):
        build.check_icons(data.ItemIcons({"w1": 'icon-x"><i>'}, PLACES))
    room = len(data.ICON_DIGITS)
    build.check_icons(data.ItemIcons({f"w{n}": f"icon-n{n}" for n in range(room - len({n for n in PLACES if n}))}, PLACES))  # (all the characters of the file, and no more)
    too_many = data.ItemIcons({f"w{n}": f"icon-n{n}" for n in range(room + 8)}, PLACES)
    with pytest.raises(build.BuildError, match=str(room)):  # a BuildError, not a traceback
        build.check_icons(too_many)


# ---- the built site: the gate -----------------------------------------------------------------------------------------------------------------------


def _fixture_with_catalog(tmp_path: Path, categories=None, mods=None) -> tuple[Path, Path]:
    """A copy of the fixture results that was made from a catalog of its own (the item table and the bundle carry the fingerprint of that file), and that catalog."""
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    path, stamped = _catalog_for(tmp_path, json.loads((results / "items.json").read_text(encoding="utf-8")), categories, mods)
    old = json.loads((RESULTS / "items.json").read_text(encoding="utf-8"))["inputs"]
    for name in ("items.json", "pal-mnk-ber/engine-l50.json"):
        text = (results / name).read_text(encoding="utf-8")
        assert old in text
        (results / name).write_text(text.replace(old, stamped["inputs"]), encoding="utf-8")
    return results, path


def _build(tmp_path: Path, **options):
    return build.build(results=options.pop("results"), out=tmp_path / "dist", noindex=True, sources_manifest=MANIFEST, changelog=make_changelog(tmp_path), **options)


def test_a_build_of_results_that_are_not_made_from_the_catalog_in_derived_stops_unless_it_is_told_not_to_use_the_catalog(tmp_path):
    need_node()
    with pytest.raises(build.BuildError, match="not the one the results were made from"):
        _build(tmp_path, results=RESULTS, without_item_catalog=False)  # (the default: the catalog in derived/, which the fixture was not made from)
    with pytest.raises(build.BuildError, match="not the one the results were made from"):
        _build(tmp_path, results=RESULTS, catalog=REPO / "derived" / "catalog.json", without_item_catalog=False)
    with pytest.raises(build.BuildError, match="opposite"):
        _build(tmp_path, results=RESULTS, catalog=REPO / "derived" / "catalog.json", without_item_catalog=True)  # (the two ask for opposite things)
    made = _build(tmp_path, results=RESULTS, without_item_catalog=True)  # the explicit way to build without it, which the release does not use
    assert made.icon_note and "--no-item-catalog" in made.icon_note and "armor" in made.icon_note


def test_the_command_line_stops_the_same_way_and_has_a_flag_that_says_plainly_that_the_pictures_of_the_armor_are_left_out(tmp_path):
    arguments = ["--results", str(RESULTS), "--out", str(tmp_path / "dist"), "--noindex", "--sources-manifest", str(MANIFEST), "--changelog", str(make_changelog(tmp_path))]
    env = {**os.environ, "PYTHONPATH": str(REPO / "pipeline"), "PYTHONUTF8": "1"}  # (a real run in a process of its own: the shim of conftest.py does not reach it)
    default = subprocess.run([sys.executable, "-m", "trioforge.site.build", *arguments], capture_output=True, text=True, cwd=REPO, env=env)
    assert default.returncode == 2 and "not the one the results were made from" in default.stderr, default.stderr
    assert len(default.stderr.strip().splitlines()) == 1
    need_node()
    flagged = subprocess.run([sys.executable, "-m", "trioforge.site.build", *arguments, "--no-item-catalog"], capture_output=True, text=True, cwd=REPO, env=env)
    assert flagged.returncode == 0, flagged.stderr
    assert "warning: " in flagged.stdout and "--no-item-catalog" in flagged.stdout
    both = subprocess.run([sys.executable, "-m", "trioforge.site.build", *arguments, "--no-item-catalog", "--catalog", str(REPO / "derived" / "catalog.json")], capture_output=True, text=True, cwd=REPO, env=env)
    assert both.returncode != 0 and "not allowed with" in both.stderr  # (argparse: one or the other)


def test_a_build_made_from_the_catalog_has_the_picture_of_the_armor_and_the_instruments_on_its_pages_and_in_its_shards(tmp_path):
    need_node()
    results, catalog = _fixture_with_catalog(tmp_path, ARMOR, MODS)
    made = _build(tmp_path, results=results, catalog=catalog, without_item_catalog=False)
    assert made.icon_note is None
    out = tmp_path / "dist"
    keys = {r["name"]: browser.record_key(r) for r in records().values()}

    def heading(name: str) -> list[list[str]]:
        html = parse((out / "item" / keys[name] / "index.html").read_text(encoding="utf-8"))
        return [sorted(n.classes) for n in html.find("h1").find_all("span")]

    assert heading("Saltmarsh Jerkin") == [["art", "art-icon-chest-leather"]]
    assert heading("Breastplate of Warding") == [["art", "art-icon-chest-plate"]]
    assert heading("Gauntlets of Endless Wrath") == [["art", "art-icon-hands-plate"]]
    assert heading("Helm of the Stoneward") == [["art", "art-icon-helm-plate"]]
    assert heading("Boots of the Wayfarer") == [["art", "art-icon-feet-leather"]]
    assert heading("Crown of the Vanguard") == [["art", "art-icon-helm"]]  # a crown of the cloth category: the place's, not the hood
    assert heading("Tinker's Awl") == [["art", "art-icon-instrument"]]
    # the trio page: the hands of the default kit
    trio = parse((out / "trio" / "pal-mnk-ber" / "index.html").read_text(encoding="utf-8"))
    rows = {row.find("th").text(skip_hidden=False): [sorted(n.classes) for n in row.find("th").find_all("span")] for row in trio.by_id("kit").find_all("tr") if row.find_all("th", scope="row")}
    assert rows["Hands"] == [["art", "art-icon-hands-plate"]]
    # the shards and the list of the browser say the same
    for path in sorted((out / "data" / "pal-mnk-ber").glob("*-*.json")):
        if path.name == "robust.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        by_key = {row[0]: name_of(document["icons"], code) for row, code in zip(document["items"], document["ic"], strict=True)}
        assert by_key.get(keys["Saltmarsh Jerkin"], "icon-chest-leather") == "icon-chest-leather", path.name
        assert by_key.get(keys["Tinker's Awl"], "icon-instrument") == "icon-instrument", path.name
        assert any(icon == "icon-chest-leather" or icon == "icon-hands-plate" for icon in by_key.values())
    listed = json.loads((out / "data" / data.ICONS_NAME).read_text(encoding="utf-8"))
    published = next((out / "assets" / "engine" / "data").glob("items-*.json"))
    table_keys = [browser.record_key(r) for r in json.loads(published.read_text(encoding="utf-8"))["items"]]
    at = table_keys.index(keys["Saltmarsh Jerkin"])
    assert name_of(listed["icons"], listed["ic"][at]) == "icon-chest-leather"
    assert name_of(listed["icons"], listed["ic"][table_keys.index(keys["Tinker's Awl"])]) == "icon-instrument"


def test_a_build_made_from_a_catalog_that_gives_no_picture_to_any_armor_stops(tmp_path):
    need_node()
    results, catalog = _fixture_with_catalog(tmp_path, {}, {})  # (the catalog is the right one, and says nothing of the fashion of any piece)
    with pytest.raises(build.BuildError, match="no armor|armor"):
        _build(tmp_path, results=results, catalog=catalog, without_item_catalog=False)


def test_one_more_byte_in_the_catalog_stops_the_build_of_results_made_from_it(tmp_path):
    need_node()
    results, catalog = _fixture_with_catalog(tmp_path, ARMOR, MODS)
    catalog.write_bytes(catalog.read_bytes() + b" ")
    with pytest.raises(build.BuildError, match="not the one the results were made from"):
        _build(tmp_path, results=results, catalog=catalog, without_item_catalog=False)


def test_a_name_that_the_browser_would_refuse_stops_the_build_with_one_line_and_so_do_too_many_icons(tmp_path, monkeypatch):
    need_node()
    monkeypatch.setattr(art, "own_icon", lambda item: "icon-Bad Name")
    with pytest.raises(build.BuildError, match="icon"):
        _build(tmp_path, results=RESULTS, without_item_catalog=True)
    count = iter(range(10_000))
    monkeypatch.setattr(art, "own_icon", lambda item: f"icon-n{next(count)}")
    monkeypatch.setattr(art, "slot_icon", lambda group: f"icon-n{next(count)}")  # (48 items and 22 places, every one a name of its own: more than a file can name when the file can name 62)
    monkeypatch.setattr(data, "ICON_DIGITS", data.ICON_DIGITS[:62])
    with pytest.raises(build.BuildError, match="62"):
        _build(tmp_path, results=RESULTS, without_item_catalog=True)


# ---- the built site -------------------------------------------------------------------------------------------------------------------------------


def _row_icons(html) -> list[tuple[str, list[str]]]:
    rows = [row for row in html.by_id("kit").find_all("tr") if row.find_all("th", scope="row")]
    return [(row.find("th").text(skip_hidden=False), [c for n in row.find("th").find_all("span") for c in sorted(n.classes) if c != "art"]) for row in rows]


def test_the_rows_of_the_kit_on_a_trio_page_show_the_picture_of_their_item(site):
    html = parse((site / "trio" / "pal-mnk-ber" / "index.html").read_text(encoding="utf-8"))
    by_name = {record["name"]: record for record in records().values()}
    icons = own_icons()
    rows = [r for r in html.by_id("kit").find_all("tr") if r.find_all("th", scope="row")]
    shown = 0
    for row, group in zip(rows, data.SLOT_INSTANCES, strict=True):
        record = by_name.get(row.find(cls="name").text(skip_hidden=False))
        key = browser.record_key(record) if record else None
        want = row_picture(icons.get(key) if key else None, group, record is not None, record["slots"] if record else ())
        spans = row.find("th").find_all("span")
        assert [sorted(n.classes) for n in spans] == ([["art", f"art-{want}"]] if want else []), (row.find("th").text(skip_hidden=False), record and record["name"])
        assert all(n.get("aria-hidden") == "true" and n.text(skip_hidden=False) == "" and not n.has("style") for n in spans)
        shown += bool(want)
    assert shown >= 12
    names = {row.find("th").text(skip_hidden=False): row for row in rows}
    assert [n.classes for n in names["Hands"].find("th").find_all("span")] == [{"art", "art-icon-hands-leather"}]  # the hands have a picture (it had none)
    assert any(n.classes - {"art"} not in ({f"art-{art.slot_icon(g)}"} for g in data.SLOT_INSTANCES) for row in names.values() for n in row.find("th").find_all("span"))  # an item's own, not a place's
    assert [n.classes for n in names["Main hand"].find("th").find_all("span")] == [{"art", "art-icon-spear"}]  # (a weapon in the main hand: its own, a pike)


def test_the_page_of_an_item_shows_the_picture_of_the_item_and_else_that_of_its_place(site):
    icons = own_icons()
    seen_own = seen_place = False
    for page in sorted((site / "item").glob("*/index.html")):
        key = page.parent.name
        record = records()[key]
        want = icons.get(key) or art.item_icon(record["slots"])
        html = parse(page.read_text(encoding="utf-8"))
        spans = html.find("h1").find_all("span")
        assert [sorted(n.classes) for n in spans] == ([["art", f"art-{want}"]] if want else []), key
        seen_own = seen_own or key in icons
        seen_place = seen_place or (key not in icons and want is not None)
    assert seen_own and seen_place


@pytest.mark.parametrize(
    ("slots", "want"),
    [
        (["WRIST", "BACK"], None),  # two worn places, two pictures: none
        (["WRIST"], "icon-wrist"),  # one worn place: its picture
        (["RANGE"], "icon-pouch"),  # a held place: never a bow, the pouch
        (["PRIMARY", "SECONDARY"], "icon-pouch"),  # two held places: neither a sword nor a bow, the pouch
        (["WRIST", "PRIMARY"], None),  # a held place and a worn one: the answer it had, none
    ],
    ids=["two-worn", "one-worn", "range", "two-held", "held-and-worn"],
)
def test_the_page_of_an_item_has_the_places_picture_only_where_every_place_it_fits_is_one_worn_place_of_one_picture(tmp_path, slots, want):
    """The cap that no kit wears (only its page shows it) is given other places. Only a worn place of one picture gives its picture, and held places only the pouch; the others have a heading without one, and the name as it was."""
    need_node()
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    changed = json.loads((results / "items.json").read_text(encoding="utf-8"))
    cap = next(r for r in changed["items"] if browser.record_key(r) == "w90040")
    cap["slots"] = slots
    (results / "items.json").write_text(json.dumps(changed), encoding="utf-8")
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=results, noindex=True)
    html = parse((out / "item" / "w90040" / "index.html").read_text(encoding="utf-8"))
    heading = html.find("h1")
    assert [sorted(n.classes) for n in heading.find_all("span")] == ([["art", f"art-{want}"]] if want else [])
    assert heading.text() == "Cap of the Archmage"  # (the name as it was, with or without a picture)
    if want is None:
        assert [n for n in html.find("main").find_all("span") if "art" in n.classes] == []
    shard = json.loads((out / "data" / "pal-mnk-ber" / "wiki-own.json").read_text(encoding="utf-8"))
    assert shard["icons"]  # (the other items of the page's shards have theirs)


def test_every_shard_of_the_site_carries_the_pictures_of_its_items_as_the_rule_gives_them(site):
    icons = row_pictures()
    checked = 0
    for path in sorted((site / "data" / "pal-mnk-ber").glob("*-*.json")):
        if path.name in ("robust.json",):
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        names = document["icons"]
        assert "sl" not in document  # (a row needs the item's own picture and its place: the shard carries no third thing)
        for row, code in zip(document["items"], document["ic"], strict=True):
            assert name_of(names, code) == icons.get(row[0]), (path.name, row[0])
            checked += 1
        assert [name_of(names, c) for c in document["pl"]] == list(PLACES)
    assert checked > 100


def test_the_site_publishes_the_list_of_icons_beside_the_item_table_it_is_made_for(site):
    name = f"data/{data.ICONS_NAME}"
    document = json.loads((site / name).read_text(encoding="utf-8"))
    published = [p for p in (site / "assets" / "engine" / "data").glob("items-*.json")]
    assert len(published) == 1
    assert document["items"] == hashlib.sha256(published[0].read_bytes()).hexdigest()  # the list is for exactly this table: the browser checks it by the digest the manifest has
    items = json.loads(published[0].read_text(encoding="utf-8"))["items"]
    assert len(document["ic"]) == len(items) and "sl" not in document
    assert len(gzip.compress((site / name).read_bytes())) < 6 * 1024 and (site / name).stat().st_size < 16 * 1024  # (the file is small: a character for each item)


def test_the_pictures_the_maintainer_drew_again_are_the_pictures_the_site_publishes_for_them(site):
    for key, want in REDRAWN.items():
        published = sorted((site / "assets").glob(f"{key}-*.png"))
        assert len(published) == 1, key
        assert pixel_digest(published[0]) == want == pixel_digest(ART / f"{key}.png"), key  # (the pixels, not the bytes: an encoder of another version writes other bytes for the same picture)
    sheet = sorted((site / "assets").glob("icons-*.png"))
    assert len(sheet) == 1 and pixel_digest(sheet[0]) == pixel_digest(ART / "icons.png")
    assert not sorted((site / "assets").glob("icon-*.png"))  # (no picture of a cell of its own)
    css = (next((site / "assets").glob("site-*.css"))).read_text(encoding="utf-8")
    assert css.count("var(--art-icons)") + css.count("--art-icons") >= 2 and ".art-icon-helm" in css


def test_the_pictures_never_change_what_a_page_says(site):
    html = parse((site / "trio" / "pal-mnk-ber" / "index.html").read_text(encoding="utf-8"))
    for row in html.by_id("kit").find_all("tr"):
        if row.find_all("th", scope="row"):
            label = row.find("th").text(skip_hidden=True)
            assert label and label == label.strip() and label[0].isalpha(), label  # the label is the same text it always was; the picture adds none


# ---- the budget of the list ---------------------------------------------------------------------------------------------------------------------------


def test_the_list_of_icons_is_held_to_its_budget_and_its_size_is_reported():
    page = "trio/pal-mnk-ber/index.html"
    files = {page: b"<html></html>", "assets/app-AAAAAAAA.js": b"let a=1;", "assets/boot-BBBBBBBB.js": b"let b=2;"}
    kwargs = dict(trio_pages=[page], first_load_assets={page: ["assets/app-AAAAAAAA.js", "assets/boot-BBBBBBBB.js"]})
    name = f"data/{data.ICONS_NAME}"
    assert (build.LIMITS["icons"], build.LIMITS["icons_gzip"]) == (16 * 1024, 6 * 1024)
    assert build.check_budgets(files, **kwargs)["icons"] == 0  # (a build with no list has none to hold)
    sizes = build.check_budgets({**files, name: b"-" * build.LIMITS["icons"]}, **kwargs)
    assert sizes["icons"] == 16 * 1024 and 0 < sizes["icons_gzip"] < 1024  # at the limit is within it
    with pytest.raises(build.BudgetError, match=r"the list of icons is 16\.0 KB \(limit 16 KB\)"):
        build.check_budgets({**files, name: b"-" * (build.LIMITS["icons"] + 1)}, **kwargs)
    noise = b"".join(hashlib.sha256(bytes([n])).digest() for n in range(240))  # 7.5 KB that gzip cannot make small: under the 16 KB raw, over the 6 KB gzipped
    assert len(noise) < build.LIMITS["icons"]
    with pytest.raises(build.BudgetError, match=r"the list of icons is \d\.\d KB gzip \(limit 6 KB\)"):
        build.check_budgets({**files, name: noise}, **kwargs)


# ---- the pouch on the built site: no filled held row is without a picture ------------------------------------------------------------------------------


def test_every_shard_names_the_pouch_for_each_held_place_and_no_item_has_it_for_its_own_picture(site):
    seen = 0
    for path in sorted((site / "data" / "pal-mnk-ber").glob("*-*.json")):
        if path.name == "robust.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        names = document["icons"]
        assert "icon-pouch" in names, path.name
        for code, group in zip(document["pl"], data.SLOT_INSTANCES, strict=True):
            assert name_of(names, code) == ("icon-pouch" if group in HELD and group != "ANY" else None if group == "ANY" else art.slot_icon(group)), (path.name, group)
        for row, code in zip(document["items"], document["ic"], strict=True):  # (the pouch is in ic for an item that fits a held place and has no picture of its own, and for no other)
            fits_held = bool({"PRIMARY", "SECONDARY", "RANGE"} & set(records()[row[0]]["slots"]))
            assert (name_of(names, code) == "icon-pouch") == (fits_held and art.own_icon(records()[row[0]]) is None), (path.name, row[1])
        seen += 1
    assert seen >= 4
    listed = json.loads((site / "data" / data.ICONS_NAME).read_text(encoding="utf-8"))
    assert "icon-pouch" in listed["icons"]
    assert [name_of(listed["icons"], code) for code in listed["pl"]] == list(PLACES)


def test_no_filled_held_row_of_any_kit_of_the_site_is_without_a_picture_and_an_empty_one_has_none(site):
    """Over every kit of every shard: a filled row of the main hand, the off hand or the range has the item's own picture or the pouch, a filled any row of an item that fits a held place has its own or the pouch,
    an any row of a worn-only item has what its page heading has (never the pouch), an empty held row none."""
    checked = {"filled": 0, "empty": 0, "any worn": 0}
    for path in sorted((site / "data" / "pal-mnk-ber").glob("*-*.json")):
        if path.name == "robust.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        names, own = document["icons"], [name_of(document["icons"], code) for code in document["ic"]]
        place = [name_of(names, code) for code in document["pl"]]
        for kit in document["kits"]:
            for index, (group, at) in enumerate(zip(data.SLOT_INSTANCES, kit, strict=True)):
                if group not in HELD:
                    continue
                if at < 0:
                    checked["empty"] += 1  # (an empty held row: the browser draws none, as the page does)
                    continue
                shown = browser_row(own[at], place, index, True)
                slots = set(records()[document["items"][at][0]]["slots"])
                if group == "ANY" and not slots & {"PRIMARY", "SECONDARY", "RANGE"}:
                    assert shown != "icon-pouch" and shown == (art.own_icon(records()[document["items"][at][0]]) or heading(sorted(slots))), (path.name, document["items"][at][1])
                    checked["any worn"] += 1
                    continue
                assert shown is not None and shown.startswith("icon-"), (path.name, group, document["items"][at][1])
                checked["filled"] += 1
    assert checked["filled"] > 50 and checked["any worn"] > 0


def test_the_rows_of_the_built_trio_page_show_the_pouch_in_a_held_place_for_an_item_with_no_picture_of_its_own(site):
    html = parse((site / "trio" / "pal-mnk-ber" / "index.html").read_text(encoding="utf-8"))
    by_name = {record["name"]: record for record in records().values()}
    icons = own_icons()
    rows = [r for r in html.by_id("kit").find_all("tr") if r.find_all("th", scope="row")]
    held_rows = 0
    for row, group in zip(rows, data.SLOT_INSTANCES, strict=True):
        if group not in HELD:
            continue
        record = by_name.get(row.find(cls="name").text(skip_hidden=False))
        spans = [sorted(n.classes) for n in row.find("th").find_all("span")]
        if record is None:
            assert spans == [], group  # (an empty held row: none)
            continue
        own = icons.get(browser.record_key(record))
        want = row_picture(own, group, True, record["slots"])
        assert spans == ([["art", f"art-{want}"]] if want else []), (group, record["name"], record["slots"])
        held_rows += 1
    assert held_rows >= 3


def test_every_held_item_of_the_fixture_has_a_picture_on_every_held_row_it_can_stand_in():
    """The table of the counts, for the fixture: own, the place's, the pouch, none; and none on a filled held row is zero."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for key, record in records().items():
        fits = {"PRIMARY", "SECONDARY", "RANGE"} & set(record["slots"])
        own = art.own_icon(record)
        for group in (*sorted(fits), "ANY"):  # (an item stands in the places it fits, and in an any row)
            picture = art.row_icon(own, group, record["slots"])
            if not fits:
                assert picture != "icon-pouch", (key, group)  # (the pouch is for an item that fits a held place)
                counts["any, worn only: " + ("own" if own else "place's" if picture else "none")] += 1
                continue
            assert picture is not None, (key, group)  # (no filled row of an item that fits a held place is without a picture)
            counts["own" if own else "pouch"] += 1
    assert counts["own"] and counts["pouch"] and counts["any, worn only: place's"] and set(counts) <= {"own", "pouch", "any, worn only: own", "any, worn only: place's", "any, worn only: none"}


def test_the_browser_knows_the_held_places_by_the_place_the_generator_puts_them_at():
    """The page code cannot tell a held place from a worn one by a picture (the file gives the pouch to the held ones and an empty held row has none), so it holds the number of the first held place; the five
    held places are the last of the 22 of a kit, and this is the generator's own order."""
    script = (REPO / "pipeline" / "trioforge" / "site" / "static" / "trio.js").read_text(encoding="utf-8")
    found = re.search(r"^const HELD_FROM = (\d+);$", script, re.MULTILINE)
    assert found is not None
    first = int(found.group(1))
    assert [group in art.HELD_PLACES for group in data.SLOT_INSTANCES] == [False] * first + [True] * (len(data.SLOT_INSTANCES) - first)
    assert len(data.SLOT_INSTANCES) - first == 5  # (the range, the two any slots, the main hand and the off hand)


# ---- the any rows: the review of 2026-11-13 ------------------------------------------------------------------------------------------------------------


def test_the_browser_keeps_the_pictures_of_the_held_things_on_held_rows_by_the_names_the_generator_has():
    """The page code holds the names of the pictures that stay on a held row (a regular expression, like the one of the armor); they are the rule's thirteen and the pouch."""
    from trioforge.site import itemicon

    script = (REPO / "pipeline" / "trioforge" / "site" / "static" / "trio.js").read_text(encoding="utf-8")
    found = re.search(r"^const HELD_PICTURE = /\^icon-\(([a-z|-]+)\)\$/;$", script, re.MULTILINE)
    assert found is not None
    assert set(found.group(1).split("|")) == set(itemicon.HELD_WORDS) | {"pouch"}
    assert HELD_PICTURES == {f"icon-{name}" for name in set(itemicon.HELD_WORDS) | {"pouch"}}


def _any_row_cases():
    return [
        ("r1", "Crimson Robe", ("CHEST",), "icon-chest"),  # a robe
        ("r2", "Cloak of Bats", ("BACK",), "icon-back"),  # a cloak
        ("r3", "Girdle of Doom", ("WAIST",), "icon-waist"),  # a girdle
        ("r4", "Lump of Coal", ("SECONDARY",), "icon-pouch"),  # a held item with no picture
        ("r5", "Straps of Two Places", ("BACK", "WRIST"), None),  # two worn places of two pictures: none
        ("r6", "Pin of the Cloak", ("BACK", "SECONDARY"), "icon-pouch"),  # it fits a held place: the pouch
        ("r7", "Wand of Smoke", ("PRIMARY", "SECONDARY"), "icon-wand"),  # its own
        ("r8", "Tsiraka's Claws", ("HANDS", "PRIMARY"), "icon-claw"),  # one of the thirteen, on an item of a worn place and a held one
    ]


def test_an_any_row_shows_the_same_for_a_robe_a_cloak_a_girdle_and_a_held_item_with_no_picture_on_the_page_in_the_data_and_in_the_browser():
    """The server row, the characters the shards and the list carry, the row the browser draws from them (an answer of the optimizer draws its rows from the list's characters in the same way), and
    the heading of the page of the item: one answer for each item, where the heading has one."""
    table = {
        "items": [
            {"key": key, "id": n, "name": name, "slots": list(slots), **({"weapon": {"skill": "1H Slashing" if key == "r7" else "Piercing", "dmg": 5, "delay": 20, "bonus": None}} if key in ("r7", "r8") else {})}
            for n, (key, name, slots, _) in enumerate(_any_row_cases(), 1)
        ]
    }
    table["items"][6]["name"] = "Wand of Smoke"
    icons = build.item_icons(table, {})
    fields = data._icon_fields([c[0] for c in _any_row_cases()], icons)
    names, codes, places = fields["icons"], fields["ic"], [name_of(fields["icons"], c) for c in fields["pl"]]
    assert places[18] is None and places[19] is None and places[17] == places[20] == places[21] == "icon-pouch"  # (the any rows have no picture of their own to give)
    for (key, name, slots, want), code in zip(_any_row_cases(), codes, strict=True):
        ic = name_of(names, code)
        record = table["items"][[c[0] for c in _any_row_cases()].index(key)]
        own = icons.of_item.get(key)
        any_server = _rows_with(_item(key, slots), "ANY", icons.of_item)["Any slot 1"]
        assert any_server == want == ic == browser_row(ic, places, 18, True) == browser_row(ic, places, 19, True), (name, any_server, want, ic)
        if not {"PRIMARY", "SECONDARY", "RANGE"} & set(slots):
            assert any_server == (own or art.item_icon(list(slots))), name  # (a worn-only item: what its page heading shows; the pouch never)
        # the other places the item can stand in: server and browser say the same
        for index, group in enumerate(data.SLOT_INSTANCES):
            if group == "ANY" or (group in HELD and group not in slots) or (group not in HELD and group not in slots):
                continue
            label = view.SLOT_LABELS[index]
            assert _rows_with(_item(key, slots), group, icons.of_item)[label] == browser_row(ic, places, index, True), (name, group)
        assert record["name"] == name
    # an empty any row has none, in the browser as on the page
    assert browser_row("icon-pouch", places, 18, False) is None and browser_row(None, places, 19, False) is None


def test_a_picture_of_the_held_things_is_on_the_held_rows_of_an_item_of_both_places_and_its_worn_row_has_the_place_s():
    claws = _item("r8", ("HANDS", "PRIMARY"))
    icons = {"r8": "icon-claw"}
    assert _rows_with(claws, "PRIMARY", icons)["Main hand"] == "icon-claw" and _rows_with(claws, "ANY", icons)["Any slot 1"] == "icon-claw"
    assert _rows_with(claws, "HANDS", icons)["Hands"] == "icon-hands-leather"  # (the place's, as at 8f9be10)
    gem = _item("r9", ("NECK", "RANGE"))
    assert _rows_with(gem, "RANGE", {"r9": "icon-stone"})["Range"] == "icon-stone" and _rows_with(gem, "NECK", {"r9": "icon-stone"})["Neck"] == "icon-neck"
    whip = _item("r10", ("PRIMARY", "SECONDARY", "WAIST"))
    assert _rows_with(whip, "WAIST", {"r10": "icon-whip"})["Waist"] == "icon-waist" and _rows_with(whip, "SECONDARY", {"r10": "icon-whip"})["Off hand"] == "icon-whip"
    for group in (g for g in data.SLOT_INSTANCES if g not in HELD):  # (a held picture on any worn row: the place's)
        for held_picture in sorted(HELD_PICTURES):
            shown = _rows_with(_item("r11", (group, "PRIMARY")), group, {"r11": held_picture})[view.SLOT_LABELS[data.SLOT_INSTANCES.index(group)]]
            assert shown == art.slot_icon(group), (group, held_picture)
