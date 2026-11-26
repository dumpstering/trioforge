"""An invented wearable that has no wiki page, for the tests that hold the code path of an item read from EQ Legends Tools alone.

An item that the site's own page lists and the wiki does not has no wiki page: its catalog key is ``rlt-<slug>``, ``wiki`` is null, it has no page id, no title and no revision, and
the export, the item pages and the sources manifest all treat it by its own rules (the record has no id and comes after every page, its match name is made of its name, its page has no
wiki credit). The catalog of 2026-11-24 has no such item any more (the wiki made a page for the last one), so the tests that need the case add this one to the real catalog in memory:
:func:`with_an_unpaged_wearable` gives a copy of a catalog document with the invented item in the order of the keys. Nothing is written anywhere.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

INVENTED_KEY = "rlt-invented-unpaged-wearable"
INVENTED_NAME = "Invented Unpaged Wearable"


def invented_unpaged_wearable(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    """The invented item: a copy of the first plain wiki-level ring of ``items`` (one slot, no weapon, no deity, not marked not-for-bis), with no wiki page, a key of its own and the origin of
    an item read from EQ Legends Tools alone."""
    base = next(
        item
        for item in sorted(items, key=lambda item: item["key"])
        if item["evidence"]["level"] == "wiki"
        and item["wiki"] is not None
        and item["slots"] == ["FINGER"]
        and not item.get("weapon")
        and not item.get("deity")
        and "not-for-bis" not in {reason["code"] for reason in item["evidence"]["reasons"]}
    )
    invented = copy.deepcopy(dict(base))
    invented.update(
        {
            "key": INVENTED_KEY,
            "name": INVENTED_NAME,
            "wiki": None,
            "origin": {"source": "eqlegendstools", "slug": "invented-unpaged-wearable", "overrides_wiki": False},
        }
    )
    return invented


def with_an_unpaged_wearable(document: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of the catalog document with the invented unpaged wearable among its items, in the order of the keys (the catalog's own)."""
    items = [copy.deepcopy(item) for item in document["items"]]
    return {**document, "items": sorted([*items, invented_unpaged_wearable(items)], key=lambda item: item["key"])}
