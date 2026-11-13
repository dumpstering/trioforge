"""The art in the pages: which slot gets which icon, what a missing asset leaves, the icon of the address bar, and that the motion of the art stops for a visitor who asked for none."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest

from trioforge.site import art, build, data, view

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "pipeline" / "trioforge" / "site" / "static"
ART = STATIC / "art"


def test_the_slot_icon_table_names_real_places_and_real_assets():
    assert set(art.SLOT_ICONS) <= set(data.SLOT_INSTANCES)
    listed = json.loads((ART / "manifest.json").read_text(encoding="utf-8"))["assets"]
    cells = {name for entry in listed.values() for name in entry.get("cells", {})}  # (the icons are the cells of one sheet)
    assert set(art.SLOT_ICONS.values()) <= set(listed) | cells


#: the places that have no icon of their own, and why: the places that hold something (the main hand, the off hand, the range, the any slots) take whatever fits, a sword and a bow are no more the
#: picture of a thing that is not one, and so an item in them has a picture only when it has one of its own (the worn places have theirs; Hands had none while its picture was a near twin of the
#: Shoulders one, and the hands now have four materials of their own and the leather ones are the place's)
NO_ICON = {"ANY", "SECONDARY", "PRIMARY", "RANGE"}


def test_a_place_with_an_icon_gets_it_and_a_place_without_gets_none():
    assert art.slot_icon("ARMS") == "icon-arms" and art.slot_icon("BACK") == "icon-back"
    assert art.slot_icon("HEAD") == "icon-helm" and art.slot_icon("FINGER") == "icon-ring"
    assert art.slot_icon("RANGE") is None and art.slot_icon("PRIMARY") is None  # (a held place: the picture of its item or none, never a sword or a bow that stands in)
    assert art.slot_icon("HANDS") == "icon-hands-leather"
    assert set(data.SLOT_INSTANCES) - set(art.SLOT_ICONS) == NO_ICON
    for group in sorted(NO_ICON):
        assert art.slot_icon(group) is None, group
    assert art.slot_icon("NOT-A-PLACE") is None
    assert len(set(art.SLOT_ICONS.values())) == len(art.SLOT_ICONS)  # one picture for each kind of place


def test_the_held_places_have_no_picture_of_their_own_and_every_worn_place_has_one():
    assert art.HELD_PLACES == {"PRIMARY", "SECONDARY", "RANGE", "ANY"}
    assert not set(art.SLOT_ICONS) & art.HELD_PLACES  # (no sword and no bow stands in for the thing in a held place)
    assert set(data.SLOT_INSTANCES) - art.HELD_PLACES == set(art.SLOT_ICONS)  # (every other place has its picture)


def test_the_part_of_the_body_a_picture_is_of():
    assert art.armor_part("icon-chest-plate") == art.armor_part("icon-chest") == "chest"
    assert art.armor_part("icon-hands-leather") == art.armor_part("icon-hands-plate") == "hands"
    assert art.armor_part("icon-helm") == art.armor_part("icon-helm-cloth") == "helm"
    for other in ("icon-ring", "icon-shield", "icon-sword-1h", "icon-chest-silk", "icon-chests", "icon-chest-plate-x", "chest", "", None, 7):
        assert art.armor_part(other) is None, other


def test_an_icon_whose_asset_is_not_part_of_the_site_is_not_given(monkeypatch):
    monkeypatch.setattr(art, "_assets", lambda: frozenset({"emblem"}))
    assert art.slot_icon("HEAD") is None and art.has("emblem") and not art.has("torch")


def test_the_kit_rows_carry_the_icon_of_their_place():
    rows = view.kit_rows(_scenario())
    assert len(rows) == len(view.SLOT_LABELS) == len(data.SLOT_INSTANCES)
    for row, group, item in zip(rows, data.SLOT_INSTANCES, _scenario().kit):
        if group == "ANY":  # (an any row shows what the item is by its places: the pouch for an item that fits a held place, the picture its page heading has for one that is worn only, none for an empty row)
            assert row.icon == (None if item is None else art.item_picture(None, item.slots)), (row.slot, group)
        elif group in art.HELD_PLACES:  # (a held place has no picture of its own: with an item in it and no picture given for the item, the pouch; with none in it, none)
            assert row.icon == (art.HELD_ICON if item is not None else None), (row.slot, group)
        else:
            assert row.icon == art.SLOT_ICONS.get(group), (row.slot, group)
    icons = {row.slot: row.icon for row in rows}
    assert icons["Head"] == "icon-helm" and icons["Ear 1"] == icons["Ear 2"] == "icon-ear" and icons["Off hand"] == "icon-pouch" and icons["Hands"] == "icon-hands-leather" and icons["Arms"] == "icon-arms"


def test_a_role_has_a_crest_only_where_one_fits(monkeypatch):
    assert art.role_crest("tank") == "crest-tank" and art.role_crest("melee") == "crest-damage"
    assert art.role_crest("balanced") is None and art.role_crest("caster") is None and art.role_crest("healer") is None
    monkeypatch.setattr(art, "_assets", lambda: frozenset())
    assert art.role_crest("tank") is None


def _scenario():
    trio = data.load_trio(REPO / "fixtures" / "site" / "results" / "pal-mnk-ber")
    return next(iter(trio.shards.values())).scenarios[0]


def test_the_favicon_is_the_32_pixel_emblem_as_a_png_address():
    assert build.FAVICON.startswith("data:image/png;base64,")
    raw = base64.b64decode(build.FAVICON.split(",", 1)[1])
    assert raw == (ART / "emblem.png").read_bytes()
    assert raw[16:24] == (32).to_bytes(4, "big") * 2  # IHDR: 32 x 32


def test_the_favicon_falls_back_to_the_drawn_logo_without_the_emblem(monkeypatch):
    monkeypatch.setattr(art, "favicon", lambda: None)
    assert build._favicon().startswith("data:image/svg+xml,")


def test_every_animation_of_the_stylesheets_is_stopped_for_reduced_motion():
    """The rule that stops motion is on every element and pseudo-element, with !important, so that no animation of the art (a sprite with steps()) can outrank it; with it stopped a sprite
    stays on its first frame (its background-position is 0 until the animation moves it)."""
    css = (STATIC / "site.css").read_text(encoding="utf-8")
    block = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}", css, re.DOTALL)
    assert block, "no reduced-motion block"
    assert re.search(r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*animation:\s*none\s*!important", block.group(1))
    sprites = (ART / "art.css").read_text(encoding="utf-8")
    for name in re.findall(r"animation:(art-[a-z0-9-]+) ", sprites):
        assert f"@keyframes {name}{{to{{background-position:" in sprites  # the first frame is where the sprite rests (position 0 0), the keyframe only moves it
        assert re.search(rf"\.{name}\{{[^}}]*background:[^;}}]* 0 0/", sprites)


def test_a_kit_with_fewer_or_more_places_than_the_page_names_is_refused_not_cut_short():
    import dataclasses

    scenario = _scenario()
    with pytest.raises(ValueError):
        view.kit_rows(dataclasses.replace(scenario, kit=scenario.kit[:-1]))
    with pytest.raises(ValueError):
        view.kit_rows(dataclasses.replace(scenario, kit=(*scenario.kit, None)))


# ---- the race pictures: one table says which race gets which picture ----------------------------------------------------------------------------------------------------

#: the races that have a picture, and the asset of each: Kerran is not here, because the only picture of a Kerran has a stray animal at its lower left that no crop of the whole figure leaves out
RACE_PICTURES = {"DWF": "race-dwarf", "OGR": "race-ogre", "FRG": "race-froglok", "IKS": "race-iksar", "GNM": "race-gnome", "ELF": "race-woodelf"}


def test_the_race_picture_table_has_exactly_the_races_that_were_picked_and_each_has_an_asset():
    from trioforge.data.races import RACE_NAMES

    assert art.RACE_PICTURES == RACE_PICTURES
    assert set(art.RACE_PICTURES) <= set(RACE_NAMES) and RACE_NAMES["ELF"] == "Wood Elf"
    listed = json.loads((ART / "manifest.json").read_text(encoding="utf-8"))["assets"]
    assert set(art.RACE_PICTURES.values()) <= set(listed)
    assert len(set(art.RACE_PICTURES.values())) == len(art.RACE_PICTURES)  # one picture for each race


def test_a_race_without_a_picture_gets_none_and_so_does_a_code_that_is_no_race():
    from trioforge.data.races import RACE_NAMES

    for code, asset in RACE_PICTURES.items():
        assert art.race_picture(code) == asset, code
    for code in sorted(set(RACE_NAMES) - set(RACE_PICTURES)):
        assert art.race_picture(code) is None, code
    assert art.race_picture("KER") is None and art.race_picture("NOT-A-RACE") is None and art.race_picture("") is None
    assert len(set(RACE_NAMES) - set(RACE_PICTURES)) == 9


def test_a_race_picture_whose_asset_is_not_part_of_the_site_is_not_given(monkeypatch):
    monkeypatch.setattr(art, "_assets", lambda: frozenset({"emblem", "race-dwarf"}))
    assert art.race_picture("DWF") == "race-dwarf" and art.race_picture("OGR") is None


def _trio_page():
    from trioforge import rules as rules_module
    from trioforge.site import content

    results = data.load_trio(REPO / "fixtures" / "site" / "results" / "pal-mnk-ber")
    book = content.load_rulebook(REPO / "rules" / "rules.json")
    return results, book, view.trio_page(results, book, view.trio_caps(results.meta.trio, results.meta.level, rules_module.load()))


def test_the_picture_of_a_trio_page_follows_its_static_best_race_and_not_the_race_the_visitor_picks():
    results, book, page = _trio_page()
    best = page.default["race"]
    assert page.race_picture == art.race_picture(best) == "race-ogre"  # the fixture's best race is the Ogre
    assert {o.code for o in page.races} > {best}  # (the page offers other races, and none of them changes the picture: it is a field of the page, made once from the default)


def test_the_trio_page_draws_the_race_picture_beside_the_best_race_line_and_nothing_when_there_is_none():
    import dataclasses

    from site_helpers import parse
    from test_site_content import render_trio

    results, book, page = _trio_page()
    head = parse(render_trio(page, book)).find(cls="page-head")
    pictures = [n for n in head.find_all("span") if "art-race-ogre" in n.classes]
    assert len(pictures) == 1 and pictures[0].get("aria-hidden") == "true" and pictures[0].text(skip_hidden=False) == "" and not pictures[0].has("style")
    assert "Best race for this trio: " in head.find(cls="best-race").text()
    bare = parse(render_trio(dataclasses.replace(page, race_picture=None), book)).find(cls="page-head")
    assert [n for n in bare.find_all("span") if any(c.startswith("art-race") for c in n.classes)] == []
    assert bare.find(cls="best-race").text() == head.find(cls="best-race").text()  # the page is whole without it


# ---- the icon beside the name of an item ------------------------------------------------------------------------------------------------------------------------------


def test_an_item_gets_the_icon_of_its_slot_only_when_every_slot_it_fits_has_the_same_one():
    assert art.item_icon(["HEAD"]) == "icon-helm" and art.item_icon(["EAR"]) == "icon-ear" and art.item_icon(["PRIMARY"]) == "icon-pouch" and art.item_icon(["RANGE"]) == "icon-pouch"
    assert art.item_icon(["HANDS"]) == "icon-hands-leather"  # (the place of the hands has its picture now)
    assert art.item_icon(["ANY"]) is None and art.item_icon(["SECONDARY"]) == "icon-pouch"  # (ANY is no place an item lists; a held place gives the pouch to an item that fits held places only)
    assert art.item_icon(["PRIMARY", "SECONDARY"]) == "icon-pouch"  # two held places: the pouch, the held row's fallback
    assert art.item_icon(["HEAD", "FACE"]) is None  # two slots, two different icons: none is the item's
    assert art.item_icon([]) is None and art.item_icon(["NOT-A-SLOT"]) is None and art.item_icon(["AMMO"]) is None
    assert art.item_icon(["EAR", "EAR"]) == "icon-ear"


def test_an_item_icon_whose_asset_is_not_part_of_the_site_is_not_given(monkeypatch):
    monkeypatch.setattr(art, "_assets", lambda: frozenset({"emblem"}))
    assert art.item_icon(["HEAD"]) is None


# ---- the pouch: the picture of a held row for an item that has none of its own -------------------------------------------------------------------------------


def test_the_pouch_is_the_fallback_of_a_held_row_and_no_item_has_it_for_its_own_picture():
    from trioforge.site import itemicon

    assert art.HELD_ICON == "icon-pouch" and art.has("icon-pouch") and art.held_icon() == "icon-pouch"
    assert "icon-pouch" not in itemicon.ALL_ICONS  # (the rule never gives an item the pouch: a held row falls back to it)
    assert "icon-pouch" not in art.SLOT_ICONS.values()  # (and a place does not have it: an empty held row has none)
    for group in sorted(art.HELD_PLACES - {"ANY"}):
        assert art.slot_icon(group) is None and art.fallback_icon(group) == "icon-pouch", group
    assert art.slot_icon("ANY") is None and art.fallback_icon("ANY") is None  # (an any row takes whatever fits: what its item is by its places decides, art.item_picture)
    for group in sorted(set(data.SLOT_INSTANCES) - art.HELD_PLACES):
        assert art.fallback_icon(group) == art.slot_icon(group) is not None, group
    assert art.fallback_icon("NOT-A-PLACE") is None


def test_a_filled_held_row_has_the_items_own_picture_else_the_pouch_and_a_worn_row_is_what_it_was():
    for group in sorted(art.HELD_PLACES - {"ANY"}):
        assert art.row_icon(None, group) == "icon-pouch", group
    for group in sorted(art.HELD_PLACES):
        assert art.row_icon("icon-wand", group) == "icon-wand", group  # (its own, wherever it stands)
        assert art.row_icon("icon-idol", group) == "icon-idol", group
        assert art.row_icon("icon-chest-plate", group) == "icon-chest-plate", group  # (a picture of armor is the item's own: the held row shows it as it always did)
    assert art.row_icon(None, "CHEST") == "icon-chest" and art.row_icon("icon-idol", "CHEST") == "icon-chest"  # (a picture of the held things stays on a held row: the worn row has the place's)
    assert art.row_icon("icon-chest-plate", "LEGS") == "icon-legs" and art.row_icon(None, "WRIST") == "icon-wrist"  # (a worn row: as before)
    assert art.row_icon(None, "NOT-A-PLACE") is None and art.row_icon("icon-idol", "NOT-A-PLACE") == "icon-idol"


def test_the_pouch_is_not_given_where_it_is_not_part_of_the_site(monkeypatch):
    monkeypatch.setattr(art, "_assets", lambda: frozenset({"emblem", "icon-wand"}))
    assert art.held_icon() is None and art.fallback_icon("PRIMARY") is None
    assert art.row_icon(None, "PRIMARY") is None and art.row_icon("icon-wand", "PRIMARY") == "icon-wand"
    assert art.item_icon(["PRIMARY"]) is None and art.item_picture(None, ["PRIMARY"]) is None and art.row_icon(None, "ANY", ["PRIMARY"]) is None


def test_the_page_of_an_item_has_the_pouch_only_for_an_item_that_fits_held_places_and_no_other():
    for held in (["PRIMARY"], ["SECONDARY"], ["RANGE"], ["PRIMARY", "SECONDARY"], ["PRIMARY", "RANGE", "SECONDARY"], ["RANGE", "SECONDARY"]):
        assert art.item_icon(held) == "icon-pouch", held
    for mixed in (["CHEST", "PRIMARY"], ["BACK", "SECONDARY"], ["NECK", "PRIMARY", "SECONDARY"], ["HANDS", "PRIMARY"], ["PRIMARY", "AMMO"], ["RANGE", "AMMO"], ["PRIMARY", "NOT-A-SLOT"]):
        assert art.item_icon(mixed) is None, mixed  # (it fits a place that is not held: today's answer, none)
    assert art.item_icon(["WRIST"]) == "icon-wrist" and art.item_icon(["BACK", "WRIST"]) is None  # (a worn item: as before)
    assert art.item_icon([]) is None and art.item_icon(["ANY"]) is None and art.item_icon(["AMMO"]) is None


# ---- the any rows: the pouch is for an item that fits a held place, and a worn-only item has what its page heading has (the review of 2026-11-13) -----------------------


def test_the_picture_an_item_has_by_its_places_is_its_own_else_the_pouch_if_it_fits_a_held_place_else_what_its_page_heading_has():
    for held in (["PRIMARY"], ["SECONDARY"], ["RANGE"], ["PRIMARY", "SECONDARY"], ["BACK", "SECONDARY"], ["WRIST", "PRIMARY"], ["NECK", "PRIMARY", "SECONDARY"], ["AMMO", "NECK", "PRIMARY"]):
        assert art.item_picture(None, held) == "icon-pouch", held  # (fits a held place and has no picture of its own: the pouch, whatever else it fits)
        assert art.item_picture("icon-wand", held) == "icon-wand", held
    assert art.item_picture(None, ["CHEST"]) == "icon-chest"  # a robe
    assert art.item_picture(None, ["BACK"]) == "icon-back"  # a cloak
    assert art.item_picture(None, ["WAIST"]) == "icon-waist"  # a girdle
    assert art.item_picture(None, ["EAR", "EAR"]) == "icon-ear" and art.item_picture(None, ["WRIST"]) == "icon-wrist"
    for worn in (["BACK", "WRIST"], ["EAR", "FINGER"], ["HEAD", "FACE", "NECK"], ["AMMO"], ["CHARM"], [], ["NOT-A-SLOT"], ["CHEST", "AMMO"]):
        assert art.item_picture(None, worn) == art.item_icon(worn), worn  # (the heading's answer, which is none for places of several pictures)
    assert art.item_picture(None, ["BACK", "WRIST"]) is None and art.item_picture(None, ["AMMO"]) is None
    assert art.item_picture("icon-chest-plate", ["CHEST"]) == "icon-chest-plate"
    for worn in (["CHEST"], ["BACK"], ["WAIST"], ["BACK", "WRIST"]):  # (a worn-only item: the picture of its heading, whatever the row)
        assert art.item_picture(None, worn) == art.item_icon(worn)


def test_an_any_row_shows_the_pouch_only_for_an_item_that_fits_a_held_place_and_else_what_the_page_heading_of_the_item_shows():
    assert art.row_icon(None, "ANY", ["CHEST"]) == "icon-chest"  # a robe
    assert art.row_icon(None, "ANY", ["BACK"]) == "icon-back"  # a cloak
    assert art.row_icon(None, "ANY", ["WAIST"]) == "icon-waist"  # a girdle
    assert art.row_icon(None, "ANY", ["BACK", "WRIST"]) is None  # a thing of two worn places of two pictures: none, as its page heading
    assert art.row_icon(None, "ANY", ["PRIMARY", "SECONDARY"]) == "icon-pouch" and art.row_icon(None, "ANY", ["RANGE"]) == "icon-pouch"
    assert art.row_icon(None, "ANY", ["BACK", "SECONDARY"]) == "icon-pouch"  # (it fits a held place: the pouch, though its heading has none)
    assert art.row_icon("icon-claw", "ANY", ["HANDS", "PRIMARY"]) == "icon-claw" and art.row_icon("icon-chest-plate", "ANY", ["CHEST"]) == "icon-chest-plate"
    assert art.row_icon(None, "ANY") is None and art.row_icon(None, "ANY", []) is None  # (nothing known of the item: no guess)
    for slots in (["CHEST"], ["BACK"], ["WAIST"], ["BACK", "WRIST"], ["WRIST"]):
        assert art.row_icon(None, "ANY", slots) == art.item_icon(slots), slots  # (the any row and the page heading say the same for a worn-only item)
    for group in ("PRIMARY", "SECONDARY", "RANGE"):
        assert art.row_icon(None, group, ["PRIMARY"]) == "icon-pouch", group  # (these places hold only what fits them: the pouch)


def test_a_picture_of_the_held_things_stays_on_a_held_row_and_a_worn_row_of_the_same_item_has_the_place_s():
    """Five items fit a held place and a worn one (Tsiraka's Claws: hands and main hand). The claw is the picture of a held row (and of the heading); on the hands row the place's picture is what it was."""
    from trioforge.site import itemicon

    held_only = {f"icon-{kind}" for kind in itemicon.HELD_WORDS} | {"icon-pouch"}
    assert art.HELD_ONLY_ICONS == held_only and len(held_only) == 14 and "icon-staff" not in held_only
    for icon in sorted(held_only):
        assert art.row_icon(icon, "HANDS", ["HANDS", "PRIMARY"]) == "icon-hands-leather", icon
        assert art.row_icon(icon, "NECK") == "icon-neck" and art.row_icon(icon, "FINGER") == "icon-ring", icon
        for group in sorted(art.HELD_PLACES):
            assert art.row_icon(icon, group, ["HANDS", "PRIMARY"]) == icon, (icon, group)
    for icon in ("icon-wand", "icon-book", "icon-instrument", "icon-orb", "icon-shield", "icon-fist", "icon-staff"):  # (the pictures the rule gave before stay on a worn row, as at 8f9be10)
        assert art.row_icon(icon, "HANDS", ["HANDS", "PRIMARY"]) == icon, icon
    assert art.row_icon("icon-chest-plate", "CHEST") == "icon-chest-plate" and art.row_icon("icon-chest-plate", "LEGS") == "icon-legs"  # (and the armor guard is as it was)
