"""Race and class tables from public sources: base attributes, class modifiers, primary classes.

``rules/races.json`` holds three things:

* the **base attributes** of the 15 playable races and the **modifiers** of the 16 classes, from
  EQL Tools' published attributes table (https://eqltools.com/attributes). Each class adds
  exactly 30 points in total, so any trio is worth 90 to any race;
* the **primary classes** of each race, from the race pages of eqlwiki, which agree with the
  developers' FAQ and the patch notes. A race restricts only the first class of a trio. One
  entry is disputed: Kerran Druid, which counts as not legal until it is confirmed;
* whether each race is ``active``.

Read the file with :func:`load`::

    data = load()
    naked_stats("OGR", ["SHD", "CLR", "SHM"], data)
    # {'STR': 145, 'STA': 152, 'AGI': 70, 'DEX': 70, 'WIS': 97, 'INT': 70, 'CHA': 47}
    legal_primaries("KER")
    # ['WAR', 'BRD', 'ROG', 'SHM', 'BST', 'BER']: Druid is disputed, so it is left out
    legal_primaries("KER", include_disputed=True)
    # ['WAR', 'DRU', 'BRD', 'ROG', 'SHM', 'BST', 'BER']

A character's naked attributes are the race's base plus the three class modifiers. They are not
capped here: players report a ceiling of 150 per attribute, and the table does not support it.

Refusing a file that drifts is the point of :func:`load`. Every problem it finds is listed in one
:class:`RacesError`: a class whose modifiers do not add up to 30, a missing, unknown or misplaced
race or class code, a stat that is not a whole number, a primary class that is unknown or out of
order, a disputed class that is not primary, a source of an unknown form, a seal the file cannot
carry, and duplicate keys or numbers that are not finite (strict JSON). The file is public, so it
may never mention a client program, an address inside one, or an offset; that is checked too.

Codes follow the project's constants: races ``HUM BAR ERU ELF HIE DEF HEF DWF TRL OGR HFL GNM IKS
KER FRG``, and classes ``WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER`` in
class-id order 1 to 16.

The package is run straight from the repository (``PYTHONPATH=pipeline``), so the default file is
found relative to this module.
"""

import datetime
import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from trioforge.classes import CLASS_CODES, CLASS_NAMES

__all__ = [
    "CLASS_CODES",
    "CLASS_POINTS",
    "RACES_PATH",
    "RACE_CODES",
    "STATS",
    "RacesError",
    "legal_primaries",
    "load",
    "naked_stats",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
RACES_PATH = REPO_ROOT / "rules" / "races.json"

STATS = ("STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA")
CLASS_POINTS = 30
MAX_BASE_STAT = 255

RACE_NAMES = {
    "HUM": "Human",
    "BAR": "Barbarian",
    "ERU": "Erudite",
    "ELF": "Wood Elf",
    "HIE": "High Elf",
    "DEF": "Dark Elf",
    "HEF": "Half Elf",
    "DWF": "Dwarf",
    "TRL": "Troll",
    "OGR": "Ogre",
    "HFL": "Halfling",
    "GNM": "Gnome",
    "IKS": "Iksar",
    "KER": "Kerran",
    "FRG": "Froglok",
}
RACE_CODES = tuple(RACE_NAMES)

# 'client' is left out: that seal means a shipped client text file, and this file cites none.
SEALS = ("developer", "measured", "player", "model")
SOURCE_KINDS = ("url", "public-text")
TOP_LEVEL_KEYS = ("version", "seal", "sources", "notes", "stat_order", "races", "classes")
SOURCE_TABLES = ("stats", "primary_classes")
RACE_KEYS = ("code", "name", "active", "base", "primary", "disputed")
CLASS_KEYS = ("code", "id", "name", "mods")

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\s\S])")
_HTTPS_URL = re.compile(r"https://[A-Za-z0-9][A-Za-z0-9.-]*(?:[/?#][^\s]*)?(?![\s\S])")
# A client program, an address inside it or an offset. Written with character classes, the way the
# rules schema writes it, because regex flags would also fold the capitals of the one case-sensitive
# word: its lowercase form sits inside ordinary words.
_CLIENT_BINARY = re.compile(r"[Ee][Qq][Gg][Aa][Mm][Ee]|\.[Ee][Xx][Ee]|R[V]A|[Oo][Ff][Ff][Ss][Ee][Tt]|0[Xx]")


class RacesError(ValueError):
    """The races file is invalid. ``problems`` lists every defect found."""

    def __init__(self, problems: list[str], source: str = "<memory>") -> None:
        self.problems = list(problems)
        self.source = source
        count = len(self.problems)
        head = f"invalid races file {source}: {count} problem{'s' if count != 1 else ''}"
        super().__init__("\n".join([head, *(f"  - {problem}" for problem in self.problems)]))


# ---- reading --------------------------------------------------------------------------------


class _StrictJsonError(ValueError):
    """JSON that parses, but that other parsers would read differently."""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError(f"duplicate key {key!r} in one object (parsers keep only the last)")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise _StrictJsonError(f"{name} is not a JSON number (use a finite number)")


def load(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Read and validate a races file; ``None`` means the repository's ``rules/races.json``.

    Returns the parsed file. Raises :class:`RacesError` if it is not valid UTF-8 / strict JSON or
    does not pass validation, and ``FileNotFoundError`` if it does not exist.
    """
    source = RACES_PATH if path is None else Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RacesError([f"not valid UTF-8: {exc}"], str(source)) from exc
    try:
        data = json.loads(
            text, object_pairs_hook=_object_without_duplicate_keys, parse_constant=_reject_constant
        )
    except json.JSONDecodeError as exc:
        raise RacesError([f"not valid JSON: {exc}"], str(source)) from exc
    except _StrictJsonError as exc:
        raise RacesError([str(exc)], str(source)) from exc
    except (RecursionError, ValueError) as exc:  # nesting too deep, or a number too long to read
        raise RacesError([f"cannot be read as JSON: {exc}"], str(source)) from exc
    problems = _problems(data, text)
    if problems:
        raise RacesError(problems, str(source))
    return data


# ---- validation -----------------------------------------------------------------------------


def _whole(value: Any) -> bool:
    return type(value) is int  # a bool is an int to Python, and 75.0 is not a whole number to us


def _problems(data: Any, text: str) -> list[str]:
    if not isinstance(data, dict):
        return ["the file must hold one JSON object"]
    problems: list[str] = []
    if _CLIENT_BINARY.search(text):
        problems.append("the file names a client binary, an address inside one or an offset; none may be public")
    for key in sorted(set(data) - set(TOP_LEVEL_KEYS)):
        problems.append(f"unknown top-level key {key!r}")
    for key in TOP_LEVEL_KEYS:
        if key not in data:
            problems.append(f"missing top-level key {key!r}")
    problems.extend(_header_problems(data))
    if "races" in data:
        problems.extend(_race_problems(data["races"]))
    if "classes" in data:
        problems.extend(_class_problems(data["classes"]))
    return problems


def _header_problems(data: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if "version" in data:
        version = data["version"]
        try:
            if not isinstance(version, str) or _DATE.fullmatch(version) is None:
                raise ValueError(version)
            datetime.date.fromisoformat(version)
        except ValueError:
            problems.append(f"version: {version!r} is not a calendar date written YYYY-MM-DD")
    if "seal" in data and data["seal"] not in SEALS:
        problems.append(f"seal: {data['seal']!r} is not one of {', '.join(SEALS)}")
    if "stat_order" in data and data["stat_order"] != list(STATS):
        problems.append(f"stat_order must be exactly {' '.join(STATS)}")
    if "notes" in data:
        notes = data["notes"]
        if not isinstance(notes, list):
            problems.append("notes must be a list of text")
        else:
            for index, note in enumerate(notes):
                if not isinstance(note, str) or not note.strip():
                    problems.append(f"notes[{index}] must be non-blank text")
    if "sources" in data:
        problems.extend(_source_problems(data["sources"]))
    return problems


def _source_problems(sources: Any) -> list[str]:
    if not isinstance(sources, dict):
        return ["sources must be an object"]
    problems = []
    for key in sorted(set(sources) - set(SOURCE_TABLES)):
        problems.append(f"sources: unknown table {key!r}")
    for table in SOURCE_TABLES:
        entries = sources.get(table)
        if not isinstance(entries, list) or not entries:
            problems.append(f"sources.{table} must list at least one source")
            continue
        for index, entry in enumerate(entries):
            label = f"sources.{table}[{index}]"
            if not isinstance(entry, dict) or set(entry) != {"kind", "ref"}:
                problems.append(f"{label} must be an object with exactly kind and ref")
                continue
            kind, ref = entry["kind"], entry["ref"]
            if kind not in SOURCE_KINDS:
                problems.append(f"{label}: unknown kind {kind!r} (use {' or '.join(SOURCE_KINDS)})")
            elif not isinstance(ref, str) or not ref.strip():
                problems.append(f"{label}: ref must be non-blank text")
            elif kind == "url" and _HTTPS_URL.fullmatch(ref) is None:
                problems.append(f"{label}: a url source must be an https:// address")
    return problems


def _code_problems(label: str, entries: list[Any], expected: tuple[str, ...]) -> list[str]:
    """Missing, unexpected, repeated or misordered codes in a list of ``{"code": ...}`` objects."""
    codes = [entry.get("code") if isinstance(entry, dict) else None for entry in entries]
    codes = [code if isinstance(code, str) else None for code in codes]
    problems = [f"{label}: missing {code!r}" for code in expected if code not in codes]
    problems += [f"{label}: unexpected code {code!r}" for code in codes if code not in expected]
    problems += [f"{label}: repeated code {code!r}" for code in dict.fromkeys(c for c in codes if codes.count(c) > 1)]
    if not problems and codes != list(expected):
        problems.append(f"{label} must be in the order {' '.join(expected)}")
    return problems


def _keys_problems(label: str, entry: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    problems = [f"{label}: unexpected key {key!r}" for key in sorted(set(entry) - set(keys))]
    problems += [f"{label}: missing key {key!r}" for key in keys if key not in entry]
    return problems


def _stat_table_problems(label: str, table: Any, minimum: int, maximum: int) -> list[str]:
    if not isinstance(table, dict):
        return [f"{label} must be an object of the seven stats"]
    problems = [f"{label}: unexpected stat {stat!r}" for stat in sorted(set(table) - set(STATS))]
    for stat in STATS:
        if stat not in table:
            problems.append(f"{label}: missing stat {stat!r}")
        elif not _whole(table[stat]) or not minimum <= table[stat] <= maximum:
            problems.append(f"{label} {stat}: must be a whole number from {minimum} to {maximum}")
    return problems


def _race_problems(races: Any) -> list[str]:
    if not isinstance(races, list):
        return ["races must be a list"]
    problems = _code_problems("races", races, RACE_CODES)
    for index, race in enumerate(races):
        code = race.get("code") if isinstance(race, dict) else None
        label = f"races[{index}] {code!r}"
        if not isinstance(race, dict):
            problems.append(f"races[{index}] must be an object")
            continue
        problems.extend(_keys_problems(label, race, RACE_KEYS))
        if isinstance(code, str) and code in RACE_NAMES and "name" in race and race["name"] != RACE_NAMES[code]:
            problems.append(f"{label}: name must be {RACE_NAMES[code]!r}")
        if "active" in race and not isinstance(race["active"], bool):
            problems.append(f"{label} active: must be true or false")
        if "base" in race:
            problems.extend(_stat_table_problems(f"{label} base", race["base"], 1, MAX_BASE_STAT))
        problems.extend(_primary_problems(label, race))
    return problems


def _primary_problems(label: str, race: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    primary = race.get("primary")
    clean = False
    if "primary" in race:
        if not isinstance(primary, list) or not primary:
            problems.append(f"{label} primary: must list at least one class")
        else:
            seen: set[str] = set()
            clean = True
            for code in primary:
                if not isinstance(code, str) or code not in CLASS_CODES:
                    problems.append(f"{label} primary: unknown class {code!r}")
                    clean = False
                elif code in seen:
                    problems.append(f"{label} primary: duplicate class {code!r}")
                    clean = False
                else:
                    seen.add(code)
            if clean and primary != sorted(primary, key=CLASS_CODES.index):
                problems.append(f"{label} primary: not in class-id order")
    if "disputed" in race:
        disputed = race["disputed"]
        if not isinstance(disputed, list):
            problems.append(f"{label} disputed: must be a list of class codes")
        else:
            for position, code in enumerate(disputed):
                if isinstance(primary, list) and code not in primary:
                    problems.append(f"{label} disputed: {code!r} is not a primary class")
                elif code in disputed[:position]:
                    problems.append(f"{label} disputed: repeated class {code!r}")
    return problems


def _class_problems(classes: Any) -> list[str]:
    if not isinstance(classes, list):
        return ["classes must be a list"]
    problems = _code_problems("classes", classes, CLASS_CODES)
    for index, klass in enumerate(classes):
        code = klass.get("code") if isinstance(klass, dict) else None
        label = f"classes[{index}] {code!r}"
        if not isinstance(klass, dict):
            problems.append(f"classes[{index}] must be an object")
            continue
        problems.extend(_keys_problems(label, klass, CLASS_KEYS))
        if "id" in klass and (not _whole(klass["id"]) or klass["id"] != index + 1):
            problems.append(f"{label}: id must be {index + 1}, found {klass['id']!r}")
        if isinstance(code, str) and code in CLASS_NAMES and "name" in klass and klass["name"] != CLASS_NAMES[code]:
            problems.append(f"{label}: name must be {CLASS_NAMES[code]!r}")
        if "mods" in klass:
            mods_problems = _stat_table_problems(f"{label} mods", klass["mods"], 0, CLASS_POINTS)
            problems.extend(mods_problems)
            if not mods_problems and sum(klass["mods"].values()) != CLASS_POINTS:
                total = sum(klass["mods"].values())
                problems.append(f"{label}: modifiers add up to {total}, not {CLASS_POINTS}")
    return problems


# ---- use ------------------------------------------------------------------------------------


def naked_stats(race: str, classes: Sequence[str], data: dict[str, Any] | None = None) -> dict[str, int]:
    """A trio's attributes with no gear and no buffs: the race's base plus the three class modifiers.

    Not capped. ``classes`` is three different class codes in any order; ``data`` is the result of
    :func:`load` (the repository file when omitted). Raises ``ValueError`` for an unknown race or
    class, or for anything but three different classes.
    """
    table = load() if data is None else data
    races = {entry["code"]: entry for entry in table["races"]}
    known = {entry["code"]: entry for entry in table["classes"]}
    if not isinstance(race, str) or race not in races:
        raise ValueError(f"unknown race {race!r}")
    trio = list(classes)
    if len(trio) != 3 or len(set(trio)) != 3:
        raise ValueError("a trio is three different classes")
    for code in trio:
        if not isinstance(code, str) or code not in known:
            raise ValueError(f"unknown class {code!r}")
    base = races[race]["base"]
    return {stat: base[stat] + sum(known[code]["mods"][stat] for code in trio) for stat in table["stat_order"]}


def legal_primaries(race_code: str, include_disputed: bool = False, data: dict[str, Any] | None = None) -> list[str]:
    """The classes a race may start a trio with, in class-id order.

    A race restricts only the first class of a trio, and these are the classes it may start with. A
    class the file marks as disputed (Kerran Druid) is left out unless ``include_disputed`` is true,
    so by default only what is confirmed counts as legal. ``data`` is the result of :func:`load` (the
    repository file when omitted). The list is the caller's own: changing it changes nothing else.
    Raises ``ValueError`` for a race code the table does not have.
    """
    table = load() if data is None else data
    races = {entry["code"]: entry for entry in table["races"]}
    if not isinstance(race_code, str) or race_code not in races:
        raise ValueError(f"unknown race {race_code!r}")
    entry = races[race_code]
    disputed = set(entry["disputed"])
    return [code for code in entry["primary"] if include_disputed or code not in disputed]
