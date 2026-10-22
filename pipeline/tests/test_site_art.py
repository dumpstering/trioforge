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
    assert set(art.SLOT_ICONS.values()) <= set(listed)


#: the places that have no icon, and why: Hands has an icon that is a near twin of the Shoulders one, Any slot takes whatever fits, and the off hand may hold a shield or a weapon
NO_ICON = {"HANDS", "ANY", "SECONDARY"}


def test_a_place_with_an_icon_gets_it_and_a_place_without_gets_none():
    assert art.slot_icon("ARMS") == "icon-arms" and art.slot_icon("BACK") == "icon-back"
    assert art.slot_icon("HEAD") == "icon-helm" and art.slot_icon("FINGER") == "icon-ring" and art.slot_icon("RANGE") == "icon-bow" and art.slot_icon("PRIMARY") == "icon-sword"
    assert set(data.SLOT_INSTANCES) - set(art.SLOT_ICONS) == NO_ICON
    for group in sorted(NO_ICON):
        assert art.slot_icon(group) is None, group
    assert art.slot_icon("NOT-A-PLACE") is None
    assert len(set(art.SLOT_ICONS.values())) == len(art.SLOT_ICONS)  # one picture for each kind of place


def test_an_icon_whose_asset_is_not_part_of_the_site_is_not_given(monkeypatch):
    monkeypatch.setattr(art, "_assets", lambda: frozenset({"emblem"}))
    assert art.slot_icon("HEAD") is None and art.has("emblem") and not art.has("torch")


def test_the_kit_rows_carry_the_icon_of_their_place():
    rows = view.kit_rows(_scenario())
    assert len(rows) == len(view.SLOT_LABELS) == len(data.SLOT_INSTANCES)
    for row, group in zip(rows, data.SLOT_INSTANCES):
        assert row.icon == art.SLOT_ICONS.get(group), (row.slot, group)
    icons = {row.slot: row.icon for row in rows}
    assert icons["Head"] == "icon-helm" and icons["Ear 1"] == icons["Ear 2"] == "icon-ear" and icons["Off hand"] is None and icons["Hands"] is None and icons["Arms"] == "icon-arms"


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
    assert art.item_icon(["HEAD"]) == "icon-helm" and art.item_icon(["EAR"]) == "icon-ear" and art.item_icon(["PRIMARY"]) == "icon-sword"
    assert art.item_icon(["HANDS"]) is None and art.item_icon(["ANY"]) is None and art.item_icon(["SECONDARY"]) is None  # a slot without an icon gives none
    assert art.item_icon(["PRIMARY", "SECONDARY"]) is None  # one slot has an icon and the other has none: no icon is claimed for the item
    assert art.item_icon(["HEAD", "FACE"]) is None  # two slots, two different icons: none is the item's
    assert art.item_icon([]) is None and art.item_icon(["NOT-A-SLOT"]) is None and art.item_icon(["AMMO"]) is None
    assert art.item_icon(["EAR", "EAR"]) == "icon-ear"


def test_an_item_icon_whose_asset_is_not_part_of_the_site_is_not_given(monkeypatch):
    monkeypatch.setattr(art, "_assets", lambda: frozenset({"emblem"}))
    assert art.item_icon(["HEAD"]) is None
