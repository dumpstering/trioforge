"""The committed catalog as the builder writes it once ``python -m trioforge.community add`` has accepted reports for some real wearables.

The first accepted report puts a strict item in ``derived/catalog.json``, which had none, and whatever assumed there was none breaks the day it lands: the fixtures, the counts and the
pages of the site. The tests that must hold then build that catalog here instead of waiting for it. The command adds the reports to a copy of the real catalog, and the evidence of
each reported item is what the ladder gives it, with the real rules and a context made as the catalog builder makes it (a report and nothing else: no seen flag, no listing); the rest
of the catalog is as it was. (A test module imports this one by its name, as it imports ``release_helpers``.)
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from trioforge import community
from trioforge.data import catalog as catalog_module
from trioforge.data import evidence as ladder
from trioforge.data.jsonio import load_strict
from trioforge.export import browser
from trioforge.precompute import grid

REPO = Path(__file__).resolve().parents[2]
DAY = "2026-10-14"  # the day of the reports: not after the day of any clock a test runs on
GONE = {"wiki-marked-not-in-eql", "wiki-marked-removed", "removed-by-patch", "removed-by-research"}


def _codes(item: dict[str, Any]) -> set[str]:
    return {reason["code"].split(":")[0] for reason in item["evidence"]["reasons"]}


def _wearable(item: dict[str, Any]) -> bool:
    return bool(grid.WEARABLE_SLOTS & set(item["slots"]))


#: the kinds of wearable a report can be made for, and the first one of the catalog that is of each kind
KINDS = {
    "live": lambda item: _wearable(item) and item["evidence"]["level"] == "wiki" and _codes(item) <= {"live-source"},  # it becomes strict, by the report alone
    "marked": lambda item: _wearable(item) and item["evidence"]["level"] == "hidden" and bool(_codes(item) & {"wiki-marked-not-in-eql", "wiki-marked-removed"}),  # it stays hidden
    "closed": lambda item: _wearable(item) and item["evidence"]["level"] == "hidden" and bool(_codes(item) & {"zone-unreleased", "zones-not-in-eql"}) and not _codes(item) & GONE,
    "disputed": lambda item: _wearable(item) and item["evidence"]["level"] == "disputed",  # it becomes strict, with a conflict-note
}


class AfterAnAdd:
    """The catalog after an accepted report for a wearable of each of the ``kinds``: ``live`` (it becomes strict), ``marked`` (the wiki marks it as gone) and ``closed`` (its zones are
    closed): they stay hidden, with the report outweighed; ``disputed`` (it becomes strict, with a ``conflict-note``). ``items`` holds the item of each kind as the catalog now has it
    (also as ``live``, ``marked``, ``closed`` and ``disputed``), ``keys`` their keys in the order of ``kinds``, ``document`` the catalog, ``path`` the file it was written to and
    ``folder`` the checkout it was made in (``folder/rules/community-seen.json`` is the list of reports)."""

    def __init__(self, folder: Path, base: dict[str, Any], kinds: tuple[str, ...] = ("live", "marked", "closed")) -> None:
        document = copy.deepcopy(base)
        items = document["items"]
        self.items = {kind: next(item for item in items if KINDS[kind](item)) for kind in kinds}
        for kind in KINDS:
            setattr(self, kind, self.items.get(kind))
        (folder / "derived").mkdir(parents=True)
        shutil.copy(REPO / "derived" / "catalog.json", folder / "derived" / "catalog.json")  # (the catalog the command reads to know a wearable)
        for issue, item in enumerate(self.items.values(), 5):
            community.add_report(folder, key=item["key"], issue=issue, kind="seen", today=DAY)
        self.folder = folder
        self.file = folder / "rules" / "community-seen.json"
        reported = catalog_module.load_community_keys(self.file)
        client = catalog_module.check_client(REPO / "derived" / "client")
        hand = ladder.load_hand_lists(REPO / "rules" / "hand-lists.json")
        context = ladder.Context(
            flagged=client.flagged, aliases=ladder.load_aliases(REPO / "rules" / "zone-aliases.json", zone_ids=client.ids), hand=hand,
            quests=ladder.QuestTable.from_data(load_strict(REPO / "derived" / "quests.json"), "quests.json"), community_keys=reported,
            out_of_era_names=ladder.out_of_era_names(items, hand), ambiguous_names=ladder.ambiguous_names(items),
        )  # fmt: skip
        for item in items:
            if item["key"] in reported:
                item["evidence"] = ladder.classify(item, context)
        self.keys = tuple(item["key"] for item in self.items.values())
        self.path = folder / "catalog-after-an-add.json"
        self.path.write_text(json.dumps(document), encoding="utf-8")
        self.document = document


def strict_without_a_report(table: Mapping[str, Any]) -> list[str]:
    """The keys of the strict records of a public item table that no community report alone made. A public catalog can have strict items, and the first accepted report makes one;
    what it can never have is a strict item that rests on a private flag (``seen-in-game``), on a listing its owner has not allowed, or on nothing public at all."""
    found = []
    for record in table["items"]:
        evidence = record["evidence"]
        codes = set(evidence.get("codes", ()))
        if evidence["level"] == "strict" and not ("community-report" in codes and not codes & {"seen-in-game", "eql-catalog"}):
            found.append(browser.record_key(record))
    return found


def evidence_of(after: AfterAnAdd, key: str) -> dict[str, Any]:
    """The evidence a catalog after an add holds for an item."""
    return next(item for item in after.document["items"] if item["key"] == key)["evidence"]
