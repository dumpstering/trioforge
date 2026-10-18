"""Synthetic releases for the tests of the results-diff report and of the release build. This module holds no tests.

A release here is the folder of the hand-written site fixture (``fixtures/site/results``: one trio, four shards, the runner-ups of three roles,
the defaults, the seals, the bundle and the item table, all with invented names and numbers) plus a ``release.json`` made by
:func:`trioforge.precompute.assemble.release_document`. The editors below change the compact files in place the way a new release would change
them: a value of a scenario, an item in a kit, a record of the item table, a swap of the runner-ups.
"""

from __future__ import annotations

import copy
import json
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from trioforge.precompute import assemble

REPO = Path(__file__).resolve().parents[2]
SITE_RESULTS = REPO / "fixtures" / "site" / "results"
SLUG = "pal-mnk-ber"
SHARDS = ("strict-own", "strict-group", "wiki-own", "wiki-group")
PLACES = (
    "HEAD FACE EAR1 EAR2 NECK SHOULDERS ARMS BACK WRIST1 WRIST2 HANDS FINGER1 FINGER2 CHEST LEGS FEET WAIST RANGE ANY1 ANY2 PRIMARY SECONDARY".split()
)
SHA_A = "a1" * 32
SHA_B = "b2" * 32
NO_ENTRIES = {"reports": [], "retracted": []}  # a release that lists its community entries and has none
#: the rules of the invented releases: ids of the real rules file with invented values, enough to say which rule a change is about
RULES = {
    "buffs.max_slots": {"value": 15, "status": "open"},
    "monk.weight_curve": {"value": {"softcap_stones": 17}, "status": "open"},
    "race.iksar_ac_bonus": {"value": 35, "status": "active"},
    "tier.stat_rule": {"value": "base + max(n, floor(base*n/10))", "status": "active"},
    "weapons.dual_wield_factor": {"value": 0.8, "status": "open"},
    "haste.cap_pct": {"value": 75, "status": "active"},
    "tier.max_fresh_drop": {"value": 4, "status": "active"},
}


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: Path, document: Any) -> None:
    Path(path).write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8", newline="\n")


def edit(path: Path, change: Callable[[Any], Any]) -> None:
    """Read a JSON file, let ``change`` mutate it (or return a new document), and write it back."""
    document = load(path)
    result = change(document)
    save(path, document if result is None else result)


def make_release(destination: Path, **over: Any) -> Path:
    """A release folder: the fixture's results and a ``release.json`` (``over`` replaces arguments of ``release_document``)."""
    shutil.copytree(SITE_RESULTS, destination)
    table = load(destination / "items.json")
    tiers = load(destination / SLUG / "wiki-own.json")["tiers"]
    values: dict[str, Any] = dict(
        tag="data-2026-10-10", catalog_date="2026-10-14", catalog_sha256=SHA_A, rules_version="2026-10-13", rules=copy.deepcopy(RULES), code_hash=SHA_B,
        solver={"canonical": True, "mip_rel_gap": 0.0, "highs": "1.15.1"}, build_options={"any_rule": "all", "haste_assumed": None}, level=50,
        game_patch="2026-09-22", trios={SLUG: tiers}, evidence=assemble.evidence_map(table), snapshot_id="cd" * 16, parity_sample="0/36",
        community=copy.deepcopy(NO_ENTRIES),
    )  # fmt: skip
    values.update(over)
    assemble.write_release_json(destination, assemble.release_document(**values))
    return destination


def change_release_json(folder: Path, **over: Any) -> None:
    """Change fields of a release folder's ``release.json`` (a field name of the document, as ``release_document`` writes it)."""
    document = assemble.read_release_json(folder)
    document.update(over)
    assemble.write_release_json(folder, document)


def report_entry(key: str, issue: int, *, kind: str = "seen", date: str = "2026-10-14") -> dict[str, Any]:
    """An entry of ``reports`` as the committed list of reports holds it (an invented key)."""
    return {"key": key, "kind": kind, "issue": issue, "date": date, "check": "item-window-screenshot"}


def retraction_entry(key: str, issue: int, *, reason: str = "withdrawn", date: str = "2026-10-15") -> dict[str, Any]:
    """An entry of ``retracted`` as the committed list of reports holds it."""
    return {"key": key, "issue": issue, "date": date, "reason": reason}


def set_community(folder: Path, reports: Sequence[Mapping[str, Any]] = (), retracted: Sequence[Mapping[str, Any]] = ()) -> None:
    """The community entries that the ``release.json`` of a release records (the release must have the field: a legacy one does not)."""
    change_release_json(folder, community={"reports": [dict(entry) for entry in reports], "retracted": [dict(entry) for entry in retracted]})


def drop_community(folder: Path) -> None:
    """Make a release a legacy one: its ``release.json`` has no ``community`` field, as the release.json of a release made before the entries were recorded."""
    document = assemble.read_release_json(folder)
    document.pop("community", None)
    assemble.write_release_json(folder, document)


class ShardFile:
    """A shard of the compact format, opened for editing: scenarios, kits and the item table of the file are changed together."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.doc = load(self.path)

    def row(self, race: str, role: str, tier: int, setup: str) -> list[Any]:
        for row in self.doc["scenarios"]:
            if row[:4] == [race, role, tier, setup]:
                return row
        raise KeyError((race, role, tier, setup))

    def rows(self, **where: Any) -> list[list[Any]]:
        names = ("race", "role", "tier", "setup")
        return [row for row in self.doc["scenarios"] if all(row[names.index(k)] == v for k, v in where.items())]

    def kit(self, row: Sequence[Any]) -> list[str | None]:
        return [None if i < 0 else self.doc["items"][i][0] for i in self.doc["kits"][row[4]]]

    def item_index(self, key: str, template: Sequence[Any] | None = None) -> int:
        for index, item in enumerate(self.doc["items"]):
            if item[0] == key:
                return index
        row = list(template) if template is not None else [key, f"Invented {key}", ["HEAD"], "drop", 4, "Quest in Lake Rathetear", "wiki", None]
        row[0] = key
        self.doc["items"].append(row)
        return len(self.doc["items"]) - 1

    def set_kit(self, row: list[Any], keys: Sequence[str | None]) -> None:
        kit = [-1 if key is None else self.item_index(key) for key in keys]
        if kit not in self.doc["kits"]:
            self.doc["kits"].append(kit)
        row[4] = self.doc["kits"].index(kit)

    def set_place(self, row: list[Any], place: str, key: str | None) -> None:
        keys = self.kit(row)
        keys[PLACES.index(place)] = key
        self.set_kit(row, keys)

    def set_value(self, row: list[Any], value: float) -> None:
        row[6] = round(row[6] + (value - row[5]), 2)  # the gain follows the value, as it would
        row[5] = value

    def drop_rows(self, keep: Callable[[list[Any]], bool]) -> None:
        self.doc["scenarios"] = [row for row in self.doc["scenarios"] if keep(row)]

    def save(self) -> None:
        save(self.path, self.doc)


class ItemTable:
    """``items.json`` of a release folder, opened for editing."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.doc = load(self.path)

    def record(self, key: str) -> dict[str, Any]:
        for record in self.doc["items"]:
            if (record.get("key") or f"w{record['id']}") == key:
                return record
        raise KeyError(key)

    def set_evidence(self, key: str, level: str, codes: Sequence[str] = ()) -> None:
        self.record(key)["evidence"] = {"level": level, **({"codes": list(codes)} if codes else {})}

    def set_stats(self, key: str, **stats: int) -> None:
        self.record(key).setdefault("stats", {}).update(stats)

    def remove(self, key: str) -> None:
        self.doc["items"] = [r for r in self.doc["items"] if (r.get("key") or f"w{r['id']}") != key]
        self.doc["count"] = len(self.doc["items"])

    def add(self, record: Mapping[str, Any]) -> None:
        self.doc["items"].append(dict(record))
        self.doc["count"] = len(self.doc["items"])

    def save(self) -> None:
        save(self.path, self.doc)


def add_invented_item(folder: Path, key: str, *, strict: bool, **stats: int) -> None:
    """A record of an invented item in the item table of a release: strict by a community entry (``strict``), or only on the wiki."""
    table = ItemTable(folder / "items.json")
    evidence = {"level": "strict", "codes": ["community-report"]} if strict else {"level": "wiki"}
    table.add(
        {"id": int(key[1:]), "name": f"Invented Community Cap {key[1:]}", "slots": ["HEAD"], "stats": stats or {"AC": 20}, "weight10": 10, "tier_rule": "drop", "evidence": evidence}
    )
    table.save()


def rename_race(folder: Path, shard_name: str, row: Sequence[Any], race: str) -> None:
    """Call a row of a shard by another race (the fixture has no Iksar): the row is found by its old name and given the new one."""
    file = ShardFile(folder / SLUG / f"{shard_name}.json")
    file.row(*row)[0] = race
    file.save()


def edit_runnerups(folder: Path, role: str, change: Callable[[dict[str, Any]], None]) -> None:
    edit(folder / SLUG / "runnerups" / f"{role}.json", change)


def runnerup_place(doc: dict[str, Any], tier: int, race: str, place: str, swaps: Sequence[tuple[str, float]]) -> None:
    """Set the swaps of one place of one view of a runner-up file (the items are added to the file's table when it lacks them)."""
    keys = [row[0] for row in doc["items"]]
    for key, _ in swaps:
        if key not in keys:
            doc["items"].append([key, f"Invented {key}", ["HEAD"], "drop", 4, "Quest in Lake Rathetear", "wiki", None])
            keys.append(key)
    for view in doc["views"]:
        if view[0] == tier and view[1] == race:
            view[3][PLACES.index(place)] = [[keys.index(key), delta] for key, delta in swaps]
            return
    raise KeyError((tier, race))


def runnerup_view(doc: dict[str, Any], tier: int, race: str) -> list[Any]:
    for view in doc["views"]:
        if view[0] == tier and view[1] == race:
            return view
    raise KeyError((tier, race))


def drop_tier(folder: Path, tier: int) -> None:
    """Take one tier out of a release: its rows in every shard, its views in every runner-up file, and the lists of tiers (the seals keep theirs)."""
    trio = folder / SLUG
    for name in SHARDS:
        shard = ShardFile(trio / f"{name}.json")
        shard.drop_rows(lambda row: row[2] != tier)
        shard.doc["tiers"] = [t for t in shard.doc["tiers"] if t != tier]
        shard.save()
    for path in sorted((trio / "runnerups").glob("*.json")):
        if path.name == "index.json":
            continue

        def change(doc: dict[str, Any]) -> None:
            doc["views"] = [view for view in doc["views"] if view[0] != tier]
            doc["tiers"] = [t for t in doc["tiers"] if t != tier]

        edit(path, change)
    change_release_json(folder, trios={SLUG: [t for t in load(trio / "wiki-own.json")["tiers"]]})


def copy_trio(folder: Path, slug: str) -> None:
    """A second trio in a release: a copy of the first (the diff reads the shards, not the names in them), listed in ``release.json``."""
    shutil.copytree(folder / SLUG, folder / slug)
    document = assemble.read_release_json(folder)
    document["trios"] = {**document["trios"], slug: list(document["trios"][SLUG])}
    document["trios"] = dict(sorted(document["trios"].items()))
    assemble.write_release_json(folder, document)


def remove_trio(folder: Path, slug: str) -> None:
    shutil.rmtree(folder / slug)
    document = assemble.read_release_json(folder)
    document["trios"] = {k: v for k, v in document["trios"].items() if k != slug}
    assemble.write_release_json(folder, document)


def pair(tmp_path: Path, *, old: Mapping[str, Any] | None = None, new: Mapping[str, Any] | None = None) -> tuple[Path, Path]:
    """Two identical releases (the second tagged a week later); ``old`` and ``new`` override arguments of ``release_document`` for one of them."""
    first = make_release(tmp_path / "old", **dict(old or {}))
    second = make_release(tmp_path / "new", **{"tag": "data-2026-10-17", "snapshot_id": "ef" * 16, **dict(new or {})})
    return first, second


def change_sources(monkeypatch, *names: str) -> None:
    """Make the source files ``names`` (relative to the ``trioforge`` package) read as if they had a line more, the way an edit of the code would: the hashes of
    the code follow it, and nothing else does."""
    root = Path(assemble.__file__).resolve().parents[1]
    targets = {(root / name).resolve() for name in names}
    real = Path.read_bytes

    def changed(path):
        data = real(path)
        return data + b"\n# a change\n" if Path(path).resolve() in targets else data

    monkeypatch.setattr(Path, "read_bytes", changed)


class FakeGit:
    """A stand-in for the questions a release build asks git (the real ones are ``release.Git``): the state of the checkout, which a test changes to see the build
    refuse it, whether a path is tracked, and whether it is ignored. ``asked`` lists the questions about paths, in order."""

    def __init__(self) -> None:
        self.head, self.status, self.diff = "a" * 40, "clean", "same"
        self.tracked_paths: set[Path] = set()
        self.unignored: list[Path] = []  # folders (or files) that git does not ignore
        self.asked: list[tuple[str, str]] = []

    def state(self) -> tuple[str, str, str]:
        return (self.head, self.status, self.diff)

    def tracked(self, path: Path) -> bool:
        self.asked.append(("tracked", str(path)))
        return Path(path) in self.tracked_paths

    def ignored(self, path: Path) -> bool:
        self.asked.append(("ignored", str(path)))
        target = Path(path)
        return not any(target == place or place in target.parents for place in self.unignored)
