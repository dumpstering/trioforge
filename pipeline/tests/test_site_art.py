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
