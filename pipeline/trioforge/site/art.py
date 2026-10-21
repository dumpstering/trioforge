"""The pixel art of the site, as the pages see it.

``static/art/manifest.json`` lists the art that exists (``scripts/art_process.py`` made its files from the artist's); the pages draw a picture only when its asset is
there, so that a page without it is whole, only plainer. The stylesheet takes the same list from ``static/art/art.css``, which the same script writes.
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path

ART_DIR = Path(__file__).resolve().parent / "static" / "art"

#: the icon of each place of a kit that has one (the place's group, as :data:`trioforge.site.data.SLOT_INSTANCES` names it, and the asset of the icon): the one table that says
#: which slot gets which picture. A place that is not here, or whose asset is not in the manifest, has none. Icons that arrive later are added here and to the manifest.
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
    "RANGE": "icon-bow",
    "PRIMARY": "icon-sword",
}  # (no icon for HANDS, whose picture is a near twin of the shoulders', for ANY, which takes whatever fits, and for SECONDARY, which may hold a shield or a weapon)

#: the crest beside a role's choice; the roles that have none (balanced: no picture fits "a blend"; caster: the crossed swords would be a false picture) get none
ROLE_CRESTS: dict[str, str] = {"tank": "crest-tank", "melee": "crest-damage"}


@lru_cache(maxsize=1)
def _assets() -> frozenset[str]:
    """The assets of the manifest whose file is there."""
    try:
        listed = json.loads((ART_DIR / "manifest.json").read_text(encoding="utf-8"))["assets"]
    except (OSError, ValueError, KeyError):
        return frozenset()
    return frozenset(name for name in listed if (ART_DIR / f"{name}.png").is_file())


def has(name: str) -> bool:
    """Whether the art ``name`` is part of the site."""
    return name in _assets()


def slot_icon(group: str) -> str | None:
    """The asset of the icon for a place of a kit (its group, ``HEAD``, ``EAR``), or None when it has no icon or the icon is not part of the site."""
    name = SLOT_ICONS.get(group)
    return name if name is not None and has(name) else None


def role_crest(role: str) -> str | None:
    """The asset of the crest for a role (``tank``, ``melee``), or None when the role has none or the crest is not part of the site."""
    name = ROLE_CRESTS.get(role)
    return name if name is not None and has(name) else None


def favicon() -> str | None:
    """The emblem as a ``data:`` address for the icon link of every page (the policy lets pictures come from the site and from ``data:``), or None without the emblem."""
    if not has("emblem"):
        return None
    return "data:image/png;base64," + base64.b64encode((ART_DIR / "emblem.png").read_bytes()).decode("ascii")
