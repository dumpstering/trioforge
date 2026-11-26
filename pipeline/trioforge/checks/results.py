"""Reading a results folder for the kit checks: the item table, and the kit of every trio, role and tier.

A results folder is what ``trioforge.precompute`` writes (``trioforge.precompute.shards`` says what each file holds): one folder for each trio (``pal-mnk-ber``) with
its four shards and its ``defaults.json``, and ``items.json`` beside them. This module reads only what the checks need, and writes nothing.

**A scenario** is one row of a shard: a race, a role, a tier, a weapon setup, a kit, its value ``F``, its totals and its optional buffs, solved for one evidence level
(the strict pool or the wiki pool) and one buff set (``own`` or ``group``). The checks do not look at every scenario: they look at **kits**, one for each trio, role and
tier, taken from the view that the page of the trio opens on:

* the evidence level that ``defaults.json`` names (``view.evidence``: ``wiki`` while the strict pool is empty, which is the case of a release);
* the buff set ``own``;
* the default race of the trio (``defaults.json``: the creation-legal race of the highest value in the default view);
* the best weapon setup of that race, role and tier: the one of the highest ``F`` (a tie goes to the setup that the shard lists first).

``items.json`` is the one place the items are read from. It is the table the site shows, with the evidence level of every item of the run, so that a kit and the pool it
was chosen from are read from the same file, and a results folder is judged by itself and not by the catalog of the checkout that runs the check.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trioforge import rules as rules_module
from trioforge.classes import CLASS_CODES
from trioforge.model.items import SLOT_GROUPS, ItemVec, at_tier
from trioforge.oldresults import other_rules_files

__all__ = [
    "BUFFS",
    "EVIDENCE_POOLS",
    "PLACE_NAMES",
    "ItemTable",
    "Kit",
    "Record",
    "Results",
    "ResultsError",
    "load_kits",
    "load_table",
    "norm_name",
    "parse_trio",
    "trio_folders",
]

BUFFS = "own"  # the buff set the kits are read at (the view the page opens on)
NOT_FOR_BIS = "not-for-bis"  # the reason code of an item that the solver leaves out (``precompute.grid.select_items``, ``site.data``)
#: the totals of a shard that the checks read: the sheet AC and the five resists
REQUIRED_TOTALS = ("ac", "fire", "cold", "magic", "poison", "disease")
#: the evidence levels an item may have to be in the solve pool of a level
EVIDENCE_POOLS: dict[str, frozenset[str]] = {"strict": frozenset({"strict"}), "wiki": frozenset({"strict", "wiki"})}
#: the slot groups an item can be worn in (an item that lists none of them, an ammunition, is no wearable)
WEARABLE_SLOTS = frozenset(name for name, _ in SLOT_GROUPS if name != "ANY")
#: what an absent field of an item record means (the table's own ``defaults`` replace these)
_DEFAULTS = {
    "classes": ["ALL"], "races": ["ALL"], "deity": None, "lore": False, "stats": {}, "sv": {}, "weapon": None, "item_type": None, "item_type_source": None,
}  # fmt: skip


class ResultsError(ValueError):
    """A results folder cannot be read: a file is missing or is not what the checks expect. The message names the file."""


def _read(path: Path) -> Any:
    try:
        with path.open("rb") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise ResultsError(f"{path.name}: not found in {path.parent.name}") from None
    except (OSError, ValueError) as error:
        raise ResultsError(f"{path.parent.name}/{path.name}: cannot be read as JSON ({type(error).__name__})") from None


def parse_trio(trio: str | Sequence[str]) -> tuple[str, ...]:
    """Three different class codes in class-id order, from ``"pal-mnk-ber"`` (any case, ``-`` or ``/``) or a sequence of codes; ``ValueError`` for anything else."""
    parts = trio.upper().replace("/", "-").split("-") if isinstance(trio, str) else [str(code).upper() for code in trio]
    if len(parts) != 3 or len(set(parts)) != 3 or any(code not in CLASS_CODES for code in parts):
        raise ValueError(f"a trio is three different class codes from {' '.join(CLASS_CODES)}, not {trio!r}")
    return tuple(sorted(parts, key=CLASS_CODES.index))


_APOSTROPHES = "'`’‘´"


def norm_name(name: str) -> str:
    """An item name as it is compared: any case, apostrophes dropped (the game writes one as a backtick), every other run of punctuation a single space.

    ``Zindrel's Fist``, ``zindrel`s fist`` and ``ZINDRELS  FIST`` are one name, and so are ``Brine-Clasped Girdle`` and ``brine clasped girdle``."""
    text = "".join(ch for ch in unicodedata.normalize("NFKC", name).casefold() if ch not in _APOSTROPHES)
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def trio_folders(root: Path | str) -> list[Path]:
    """The folders of the trios under a results folder, in the order of their names (a folder is a trio when its name parses as three classes)."""
    found = []
    for path in sorted(Path(root).iterdir(), key=lambda p: p.name):  # by the text of the name: a path compares by case on one system and not on another
        if path.is_dir():
            try:
                parse_trio(path.name)
            except ValueError:
                continue
            found.append(path)
    return found


@dataclass(frozen=True)
class Record:
    """One item of the table, with what the checks ask of it read once."""

    key: str
    name: str
    slots: frozenset[str]
    classes: frozenset[str] | None  # None: every class
    races: frozenset[str] | None  # None: every race
    deity: tuple[str, ...] | None
    level: str
    lore: bool  # a Lore item may be worn once
    not_for_bis: bool  # the evidence ladder marks it: temporary, or a quest takes it on hand-in; the solver leaves it out whatever its level says
    catalog: Mapping[str, Any]  # the dict that ``at_tier`` reads


def _record(raw: Mapping[str, Any]) -> Record:
    key = raw.get("key") or f"w{raw['id']}"
    weight10 = raw.get("weight10")
    catalog = {
        "key": key, "name": raw["name"], "slots": list(raw["slots"]), "classes": list(raw["classes"]), "races": list(raw["races"]),
        "deity": None if raw["deity"] is None else list(raw["deity"]), "flags": ["lore"] if raw["lore"] else [],
        "stats": dict(raw["stats"]), "sv": dict(raw["sv"]), "weight": None if weight10 is None else weight10 / 10,
        "weapon": None if raw["weapon"] is None else dict(raw["weapon"]), "item_type": raw["item_type"],
        "item_type_source": raw["item_type_source"], "tier_rule": raw["tier_rule"],
    }  # fmt: skip
    classes = None if any(str(c).upper() == "ALL" for c in raw["classes"]) else frozenset(raw["classes"])
    races = None if any(str(r).upper() == "ALL" for r in raw["races"]) else frozenset(raw["races"])
    return Record(
        key=key, name=raw["name"], slots=frozenset(raw["slots"]), classes=classes, races=races,
        deity=None if raw["deity"] is None else tuple(raw["deity"]), level=raw["evidence"]["level"], lore=bool(raw["lore"]),
        not_for_bis=NOT_FOR_BIS in (raw["evidence"].get("codes") or ()), catalog=catalog,
    )  # fmt: skip


class ItemTable:
    """The item table of a results folder (``items.json``): every wearable with its evidence level, and its numbers at any tier.

    ``vec(key, tier)`` is the item as the model sees it at a tier (``trioforge.model.items.at_tier``; the result is kept, so an item is made once for a tier);
    ``pool(evidence)`` the records the solver may use at all: the level of the pool, no deity lock, not marked ``not-for-bis`` and a slot the model has (hidden and disputed
    items are in no pool); ``eligible(trio, race, evidence)`` the records of that pool that a trio and a race can wear, which is the pool a kit of that view was chosen
    from: a class of the trio and the race besides."""

    def __init__(self, document: Mapping[str, Any], rules: Any = None) -> None:
        if not isinstance(document, Mapping) or not isinstance(document.get("items"), list):
            raise ResultsError("items.json: not an item table (it has no list of items)")
        self.rules = rules_module.load() if rules is None else rules
        fill = {**_DEFAULTS, **(document.get("defaults") or {})}
        self.records: dict[str, Record] = {}
        self._names: dict[str, list[str]] = {}
        for raw in document["items"]:
            try:
                record = _record({**fill, **raw})
            except (KeyError, TypeError, ValueError) as error:
                raise ResultsError(f"items.json: an item record cannot be read ({type(error).__name__})") from None
            self.records[record.key] = record
            self._names.setdefault(norm_name(record.name), []).append(record.key)
        self._vecs: dict[tuple[str, int], ItemVec] = {}
        self._open: dict[str, list[Record]] = {}
        self._pools: dict[tuple[tuple[str, ...], str, str], list[Record]] = {}

    def __len__(self) -> int:
        return len(self.records)

    def vec(self, key: str, tier: int) -> ItemVec:
        """The item ``key`` at ``tier`` (0 to 10)."""
        found = self._vecs.get((key, tier))
        if found is None:
            try:
                found = self._vecs[(key, tier)] = at_tier(self.records[key].catalog, tier, self.rules)
            except (TypeError, ValueError) as error:
                raise ResultsError(f"the item {self.records[key].name!r} cannot be read at tier +{tier}: {error}") from None
        return found

    def pool(self, evidence: str) -> list[Record]:
        """The records of the solve pool of ``evidence`` (see the class), whatever the trio and the race, in key order."""
        found = self._open.get(evidence)
        if found is None:
            levels = EVIDENCE_POOLS[evidence]
            found = self._open[evidence] = sorted(
                (r for r in self.records.values() if r.level in levels and r.deity is None and not r.not_for_bis and r.slots & WEARABLE_SLOTS), key=lambda r: r.key
            )
        return found

    def eligible(self, trio: Sequence[str], race: str, evidence: str) -> list[Record]:
        """The records of the solve pool of ``evidence`` that a character of ``trio`` and ``race`` can wear, in key order."""
        team = tuple(sorted(trio))
        found = self._pools.get((team, race, evidence))
        if found is None:
            classes = frozenset(team)
            found = self._pools[(team, race, evidence)] = [
                r for r in self.pool(evidence) if (r.classes is None or r.classes & classes) and (r.races is None or race in r.races)
            ]
        return found

    def keys_named(self, name: str) -> list[str]:
        """The keys of the items that carry ``name``, compared as :func:`norm_name` compares."""
        return list(self._names.get(norm_name(name), ()))


def load_table(root: Path | str, rules: Any = None) -> ItemTable:
    """The item table of the results folder ``root``."""
    return ItemTable(_read(Path(root) / "items.json"), rules)


def _place_names() -> tuple[str, ...]:
    """``EAR1`` and ``EAR2`` for a group of two places, the group's own name for a group of one: the names that a shard gives its ``places``."""
    names: list[str] = []
    for group, count in SLOT_GROUPS:
        names.extend([group] if count == 1 else [f"{group}{n}" for n in range(1, count + 1)])
    return tuple(names)


PLACE_NAMES: tuple[str, ...] = _place_names()


@dataclass(frozen=True)
class Kit:
    """The kit of one trio, role and tier (the module docstring says which view it is taken from).

    ``places`` is the item key, or None, for each of the 22 places of ``PLACE_NAMES``; ``totals`` the sheet totals of the shard (``ac`` is the sheet AC, the five
    resists are the counted ones); ``softcap`` the sheet AC softcap of the trio."""

    slug: str
    trio: tuple[str, ...]
    role: str
    tier: int
    race: str
    setup: str
    evidence: str
    value: float
    places: tuple[str | None, ...]
    totals: Mapping[str, int]
    softcap: int
    level: int = 50
    buff_ids: tuple[int, ...] = ()  # the optional buffs the solver chose (spell ids)
    setups: tuple[str, ...] = ()  # the weapon setups the shard (the evidence level) has for the kit's role, sorted: what the level offers, of which the kit's own setup is the best
    procs: tuple[tuple[Any, ...], ...] = ()  # the weapon procs the kit counts, ``(hand, name, donor, mode, value)`` (:func:`trioforge.model.procs.record`); none in results made before procs

    def worn(self) -> list[tuple[str, str]]:
        """``(place, key)`` of every place that holds an item, in the order of the places."""
        return [(place, key) for place, key in zip(PLACE_NAMES, self.places, strict=True) if key is not None]


def _check_procs(name: str, shard: Mapping[str, Any]) -> None:
    """A shard's ``procs`` key must have an index for every scenario and every index must be -1 or a row that is there: a key that does not is refused whole, whichever scenarios
    the checks read."""
    table = shard.get("procs")
    if table is None:
        return
    rows, at = table.get("rows") if isinstance(table, Mapping) else None, table.get("at") if isinstance(table, Mapping) else None
    if not isinstance(rows, list) or not isinstance(at, list):
        raise ResultsError(f"{name}: its procs have no list of rows and no list of indexes")
    if len(at) != len(shard["scenarios"]):
        raise ResultsError(f"{name}: its procs have {len(at)} indexes for {len(shard['scenarios'])} scenarios")
    for number, index in enumerate(at):
        if type(index) is not int or not -1 <= index < len(rows):
            raise ResultsError(f"{name}: procs.at[{number}] is {index!r}, which is neither -1 nor a row of its procs")


def _procs_of(shard: Mapping[str, Any], number: int) -> tuple[tuple[Any, ...], ...]:
    """The procs the scenario ``number`` of a shard counts (its ``procs`` key, see :mod:`trioforge.precompute.shards`): none for a shard without the key."""
    table = shard.get("procs")
    if not table:
        return ()
    index = table["at"][number]
    return () if index < 0 else tuple(tuple(entry) for entry in table["rows"][index])


def _kits_of(folder: Path, evidence: str | None, buffs: str, race: str | None) -> list[Kit]:
    defaults = _read(folder / "defaults.json")
    level = evidence or (defaults.get("view") or {}).get("evidence") or "wiki"
    if level not in EVIDENCE_POOLS:
        raise ResultsError(f"{folder.name}/defaults.json: the evidence level {level!r} is not one of {', '.join(EVIDENCE_POOLS)}")
    race = race or defaults.get("race")
    if not isinstance(race, str):
        raise ResultsError(f"{folder.name}/defaults.json: it names no default race")
    name = f"{folder.name}/{level}-{buffs}.json"
    shard = _read(folder / f"{level}-{buffs}.json")
    try:
        trio = parse_trio(shard["trio"])
        if tuple(shard["places"]) != PLACE_NAMES:
            raise ResultsError(f"{name}: its places are not the 22 that the checks know")
        keys = [row[0] for row in shard["items"]]
        _check_procs(name, shard)
        order = {role: {setup: n for n, setup in enumerate(setups)} for role, setups in shard["setups"].items()}
        rows: dict[tuple[str, int], list[tuple[int, Any]]] = {}
        level_setups: dict[str, set[str]] = {}  # the setups the level has for each build, over every race and tier
        for number, row in enumerate(shard["scenarios"]):
            level_setups.setdefault(row[1], set()).add(row[3])
            if row[0] == race:
                rows.setdefault((row[1], row[2]), []).append((number, row))
        kits = []
        for (role, tier), candidates in rows.items():
            number, row = min(candidates, key=lambda c: (-c[1][5], order.get(c[1][1], {}).get(c[1][3], len(order))))
            totals = dict(zip(shard["totals_keys"], shard["totals"][row[7]], strict=True))
            lacking = [key for key in REQUIRED_TOTALS if key not in totals]
            if lacking:
                raise ResultsError(f"{name}: its totals lack {', '.join(lacking)}")
            kits.append(
                Kit(
                    slug=folder.name, trio=trio, role=role, tier=tier, race=race, setup=row[3], evidence=level, value=row[5],
                    places=tuple(None if index < 0 else keys[index] for index in shard["kits"][row[4]]), totals=totals,
                    softcap=int(shard["caps"]["sheet_softcap"]), level=int(shard.get("level", 50)),
                    buff_ids=tuple(shard["buff_sets"][row[8]]) if shard.get("buff_sets") else (), procs=_procs_of(shard, number),
                    setups=tuple(sorted(level_setups[role])),
                )  # fmt: skip
            )
        roles = list(shard["roles"])
    except ResultsError:
        raise
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        raise ResultsError(f"{name}: not a shard the checks can read") from None
    return sorted(kits, key=lambda kit: (roles.index(kit.role) if kit.role in roles else len(roles), kit.tier))


class Results:
    """A results folder: its item table and the kits of its trios (the module docstring says which scenario of a trio is its kit).

    ``kits(trio, race)`` reads one trio's shard at one race (the trio's default race when ``race`` is None) and keeps what it read. ``evidence`` replaces the level that
    the default view of each trio names (``strict`` or ``wiki``); a pool of the level that is empty gives kits of nothing at all, which the checks count as they
    count any other kit."""

    def __init__(self, root: Path | str, *, evidence: str | None = None, buffs: str = BUFFS, rules: Any = None) -> None:
        self.root = Path(root)
        if not self.root.is_dir():
            raise ResultsError(f"{self.root.name or os.fspath(self.root)}: not a folder")
        self.folders = {parse_trio(folder.name): folder for folder in trio_folders(self.root)}
        if not self.folders:
            raise ResultsError(f"{self.root.name}: no folder named like a trio (pal-mnk-ber) in it")
        self.evidence, self.buffs = evidence, buffs
        document = _read(self.root / "items.json")
        self.table = ItemTable(document, rules)
        self.release = {key: document.get(key) for key in ("data_release", "rules_version")}
        self._kits: dict[tuple[tuple[str, ...], str | None], list[Kit]] = {}
        self._mismatch: tuple[str, str] | None | bool = False  # (False: not asked yet)
        self.unread: list[str] = []  # the trios (folder names) that gave no kit when :meth:`all_kits` was read to its end

    def rules_mismatch(self) -> tuple[str, str] | None:
        """``(the rules version of the results, the rules version of this checkout)`` when they differ, else None: the checks read the model, the rules and the race table of
        the checkout, so results made with other rules are valued by rules that did not make them. The results are of other rules when ``items.json`` says so or when **any** file of
        any trio's folder does (:func:`trioforge.oldresults.other_rules_files`: a file that records another version, or none where a writer makes one): the item table of today's
        rules over a trio folder of older rules is a folder of older rules. The version given is the first that differs (``"none"`` for a file that records none)."""
        if self._mismatch is False:
            made, here = self.release.get("rules_version"), getattr(self.table.rules, "version", None)
            found: tuple[str, str] | None = None if made == here else (str(made), str(here))
            if found is None and here is not None:
                for folder in self.folders.values():
                    other = other_rules_files(folder, str(here))
                    if other:
                        found = ("none" if other[0][1] is None else other[0][1], str(here))
                        break
            self._mismatch = found
        return self._mismatch  # type: ignore[return-value]

    def _held(self, kits: list[Kit]) -> list[Kit]:
        """``kits``, after a check that every item they wear is in the item table: a shard and a table of two runs would not agree, and no check can read such a kit."""
        for kit in kits:
            if any(key is not None and key not in self.table.records for key in kit.places):
                raise ResultsError(f"{kit.slug}: its shard wears an item that items.json does not have")
        return kits

    def trios(self) -> list[tuple[str, ...]]:
        """The trios of the folder, in the order of their folder names."""
        return list(self.folders)

    def kits(self, trio: Sequence[str] | str, race: str | None = None) -> list[Kit]:
        """The kits of one trio (role by role, tier by tier); none for a trio the folder lacks."""
        codes = parse_trio(trio)
        race = race.upper() if race else None
        found = self._kits.get((codes, race))
        if found is None:
            folder = self.folders.get(codes)
            found = self._kits[(codes, race)] = [] if folder is None else self._held(_kits_of(folder, self.evidence, self.buffs, race))
        return found

    def all_kits(self) -> Iterator[Kit]:
        """Every kit of the folder, trio by trio, role by role, tier by tier. A trio's kits are not kept once it has been passed; a trio that gave none is put in
        :attr:`unread`."""
        self.unread = []
        for folder in self.folders.values():
            found = self._held(_kits_of(folder, self.evidence, self.buffs, None))
            if not found:
                self.unread.append(folder.name)
            yield from found


def load_kits(root: Path | str, *, evidence: str | None = None, buffs: str = BUFFS) -> Iterator[Kit]:
    """Every kit of a results folder (see :class:`Results`), without its item table."""
    root = Path(root)
    if not root.is_dir():
        raise ResultsError(f"{root.name or os.fspath(root)}: not a folder")
    folders = trio_folders(root)
    if not folders:
        raise ResultsError(f"{root.name}: no folder named like a trio (pal-mnk-ber) in it")
    for folder in folders:
        yield from _kits_of(folder, evidence, buffs, None)
