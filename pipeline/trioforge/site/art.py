"""The pixel art of the site, as the pages see it.

``static/art/manifest.json`` lists the art that exists (``scripts/art_process.py`` made its files from the artist's); the pages draw a picture only when its asset is
there, so that a page without it is whole, only plainer. The stylesheet takes the same list from ``static/art/art.css``, which the same script writes. The small icons of the places and
the items are the cells of one sheet (``icons``): a cell is an asset of the site as a still is, drawn by the class ``art-<name>``, and its picture is part of the sheet's file.
"""

from __future__ import annotations

import base64
import json
import re
from functools import lru_cache
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trioforge.site import itemicon

ART_DIR = Path(__file__).resolve().parent / "static" / "art"

#: the most the art of the site may weigh on the wire together (the PNGs are already compressed, so their size is what is sent): the one place that says it. The build holds the site to it (``LIMITS["art"]``) and
#: ``scripts/art_process.py`` holds what it made to it. It was 120 KB for the theme; the set pieces and the race pictures raised it to 200 KB (DECISIONS.md, the entry of the set pieces), and the pictures of the
#: items (the sheet of icons, and the three pictures drawn again) to 210 KB (DECISIONS.md, the entry of the item icons), and the fourteen pictures of the held things (and the pouch) that were added to the sheet to
#: 215 KB (DECISIONS.md, the entry of the held icons). What a *phone* is sent on any one page stays under 120 KB, which tests-e2e/art-phone.spec.mjs holds, because a scene that is not shown on a phone is never fetched.
BUDGET_BYTES = 215 * 1024

#: the places that hold something in a hand, at range or anywhere: what stands in them is whatever fits, so the picture of a row of one is the item's own picture, else the pouch (:data:`HELD_ICON`); no sword
#: and no bow stands in for an item that has none (:func:`row_icon`). Every other place of a kit is a worn place, which has a picture of its own.
HELD_PLACES = frozenset({"PRIMARY", "SECONDARY", "RANGE", "ANY"})

#: the picture of a filled row of a held place whose item has no picture of its own, so that no filled held row is without one (the maintainer's pouch, 2026-11-13). It is the *fallback of a row* and no item's
#: own picture: the rule of :mod:`trioforge.site.itemicon` never gives it, it is not in :data:`SLOT_ICONS` (an empty held row has none), and a worn row never has it.
HELD_ICON = "icon-pouch"

#: the pictures that belong to a held row: the thirteen pictures of the held things (:data:`trioforge.site.itemicon.HELD_WORDS`) and the pouch. On a worn row an item shows the place's picture instead (an item that
#: fits the hands and the main hand has the claw in the main hand and the leather glove of the hands on the hands row, as at 8f9be10); the heading of the page of the item has the picture all the same. This is the
#: mechanism that keeps an own picture of armor in the place of its own part, for these pictures.
HELD_ONLY_ICONS = frozenset({f"icon-{kind}" for kind in itemicon.HELD_WORDS} | {HELD_ICON})

#: the icon of each worn place of a kit (the place's group, as :data:`trioforge.site.data.SLOT_INSTANCES` names it, and the asset of the icon): the one table that says which picture a worn place gets
#: when the item in it has none of its own (:func:`own_icon`: the picture of what the item is). A place that is not here, or whose asset is not in the manifest, has none; the held places are not here.
#: Icons that arrive later are added here and to the manifest.
SLOT_ICONS: dict[str, str] = {
    "HEAD": "icon-helm",
    "FACE": "icon-face",
    "EAR": "icon-ear",
    "NECK": "icon-neck",
    "SHOULDERS": "icon-shoulders",
    "ARMS": "icon-arms",
    "BACK": "icon-back",
    "WRIST": "icon-wrist",
    "FINGER": "icon-ring",
    "CHEST": "icon-chest",
    "LEGS": "icon-legs",
    "FEET": "icon-feet",
    "WAIST": "icon-waist",
    "HANDS": "icon-hands-leather",
}  # (no icon for the held places, which take whatever fits: the main hand, the off hand, the range and the any slots; a thing in them has the picture of its own, else the pouch (HELD_ICON), and the bow is
#    the own picture of an archery weapon, as the sword is of a sword. HANDS had none while its picture was a near twin of the shoulders'; the pictures of the hands are now in four materials, and
#    the leather ones are the place's)

#: the crest beside a build's choice; the builds that have none (the Shield caster, the Caster tank and the Caster, the casting ones: the crossed swords would be a false picture, and the Archer has no crest either) get none
ROLE_CRESTS: dict[str, str] = {"tank": "crest-tank", "melee": "crest-damage"}


#: the picture beside the line "Best race for this trio" for each race that has one (the race's code, as :data:`trioforge.data.races.RACE_NAMES` has it, and the asset): the one table that says which race gets which
#: picture. Every other race has none. Kerran is not here on purpose: the only picture of a Kerran has a stray small animal at its lower left that no crop that keeps the whole figure can leave out.
RACE_PICTURES: dict[str, str] = {
    "DWF": "race-dwarf",
    "OGR": "race-ogre",
    "FRG": "race-froglok",
    "IKS": "race-iksar",
    "GNM": "race-gnome",
    "ELF": "race-woodelf",
}


@lru_cache(maxsize=1)
def _assets() -> frozenset[str]:
    """The assets of the manifest whose file is there."""
    try:
        listed = json.loads((ART_DIR / "manifest.json").read_text(encoding="utf-8"))["assets"]
    except (OSError, ValueError, KeyError):
        return frozenset()
    found = {name for name in listed if (ART_DIR / f"{name}.png").is_file()}
    for name in tuple(found):  # (a cell of a sheet has no file of its own: it is there when its sheet is)
        cells = listed[name].get("cells") if isinstance(listed[name], dict) else None
        if isinstance(cells, dict):
            found.update(cells)
    return frozenset(found)


def has(name: str) -> bool:
    """Whether the art ``name`` is part of the site."""
    return name in _assets()


def slot_icon(group: str) -> str | None:
    """The asset of the icon for a place of a kit (its group, ``HEAD``, ``EAR``), or None when it has no icon or the icon is not part of the site."""
    name = SLOT_ICONS.get(group)
    return name if name is not None and has(name) else None


def held_icon() -> str | None:
    """The asset of the pouch, the picture of a held row whose item has none of its own, or None when it is not part of the site."""
    return HELD_ICON if has(HELD_ICON) else None


def fallback_icon(group: str) -> str | None:
    """The picture a filled row of a place shows for an item that has none of its own: the place's picture (:func:`slot_icon`) in a worn place, the pouch (:func:`held_icon`) in the main hand, the off hand
    and the range, none in an any row (it takes whatever fits, so what the item is by its places decides: :func:`item_picture`), or None when the place is none of these or the art is not part of the site.
    An empty row is :func:`slot_icon`: the pouch is for a row that has an item."""
    if group == "ANY":
        return None
    return held_icon() if group in HELD_PLACES else slot_icon(group)


def role_crest(role: str) -> str | None:
    """The asset of the crest for a role (``tank``, ``melee``), or None when the role has none or the crest is not part of the site."""
    name = ROLE_CRESTS.get(role)
    return name if name is not None and has(name) else None


def race_picture(race: str) -> str | None:
    """The asset of the picture for a race (its code, ``DWF``, ``OGR``), or None when the race has none or the picture is not part of the site."""
    name = RACE_PICTURES.get(race)
    return name if name is not None and has(name) else None


def own_icon(item: Mapping[str, Any]) -> str | None:
    """The asset of the icon of what the item is (:func:`trioforge.site.itemicon.icon_name`, the one rule that says it), or None where nothing says plainly or the icon is not part of the site;
    the page then draws the icon of the item's place (:func:`slot_icon`, :func:`item_icon`)."""
    name = itemicon.icon_name(item)
    return name if name is not None and has(name) else None


def item_icon(slots: Sequence[str]) -> str | None:
    """The asset of the icon for the page of an item that has none of its own, from the places it fits (its slot groups, as the item table lists them): the pouch when it fits held places only (the main
    hand, the off hand, the range: every row it can stand in is a held row, which has the pouch for it), the icon of its place when every place it fits is a worn place and they all have the same
    one, and None otherwise (no place, a held place and a worn one, a place without an icon, or places with different icons: no picture is claimed for it) or when the icon is not part of the site."""
    if slots and all(slot in itemicon.HELD_SLOTS for slot in slots):
        return held_icon()
    icons = {SLOT_ICONS.get(slot) for slot in slots}
    if len(icons) != 1:
        return None
    name = next(iter(icons))
    return name if name is not None and has(name) else None


def item_picture(own: str | None, slots: Sequence[str]) -> str | None:
    """The picture an item has where the place it stands in does not decide, as an any row does not (and what the data files' ``ic`` says of it): its own picture (``own``), else the pouch when it fits a held
    place (the main hand, the off hand, the range: the pouch is only for an item that fits one), else what the page of the item shows (:func:`item_icon`: the place's picture when every place it fits is a
    worn place of one picture, none otherwise); None for an item that fits no place and has no picture."""
    if own is not None:
        return own
    if any(slot in itemicon.HELD_SLOTS for slot in slots):
        return held_icon()
    return item_icon(slots)


_ARMOR_PICTURE = re.compile(
    r"icon-(" + "|".join(sorted(set(itemicon.ARMOR_PARTS.values()))) + r")(?:-(?:" + "|".join(sorted(set(itemicon.MATERIALS.values()))) + r"))?"
)


def armor_part(icon: str | None) -> str | None:
    """The part of the body (``helm``, ``chest``, ``arms``, ``legs``, ``feet``, ``hands``) that a picture of armor, or the picture of the place of a part, is of, or None for any other picture:
    ``icon-chest-plate`` and ``icon-chest`` are of the chest, ``icon-hands-leather`` of the hands, ``icon-ring`` of none."""
    found = _ARMOR_PICTURE.fullmatch(icon) if isinstance(icon, str) else None
    return found.group(1) if found else None


def row_icon(own: str | None, group: str, slots: Sequence[str] | None = None) -> str | None:
    """The picture beside a place of the kit for the item in it (its own picture, ``own``, or None; the place's group; the places the item fits, ``slots``, which only an any row needs): **a worn place** has
    the item's own picture, else its own place's picture, always (the other places the item fits do not matter), except that **a picture of the held things** (:data:`HELD_ONLY_ICONS`) stays on a held row
    (the place's picture instead) and **a picture of armor** stays in the place of its own part (a chest picture is never on the row of the legs: another worn place has its own picture instead);
    **the main hand, the off hand and the range** have the item's own picture, else the pouch (:data:`HELD_ICON`), so that no filled row of them is without a picture and no sword or bow ever stands in for a
    thing that is none; **an any row** takes whatever fits, so it has what the item is by its places (:func:`item_picture`: its own, else the pouch if it fits a held place, else what its page heading shows,
    and nothing where the places are not known). This is the row of an item: an empty place has :func:`slot_icon` (its own picture in a worn place, none in a held one). The page of the item asks
    :func:`item_icon` and not this; ``static/trio.js`` (``rowIcon``) says the same for the rows it draws again from the data files' ``ic``, and the tests hold the two to each other."""
    if group == "ANY":
        return item_picture(own, slots or ())
    if group in HELD_PLACES:
        return own if own is not None else held_icon()
    place = slot_icon(group)
    if place is None:  # (a place that is none of the kit's: nothing to put in its place)
        return own
    if own is None or own in HELD_ONLY_ICONS:
        return place
    part = armor_part(own)
    return place if part is not None and part != armor_part(place) else own


def favicon() -> str | None:
    """The emblem as a ``data:`` address for the icon link of every page (the policy lets pictures come from the site and from ``data:``), or None without the emblem."""
    if not has("emblem"):
        return None
    return "data:image/png;base64," + base64.b64encode((ART_DIR / "emblem.png").read_bytes()).decode("ascii")
