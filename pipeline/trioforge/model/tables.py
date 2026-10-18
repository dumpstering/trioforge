"""The model's lookup tables, read once and kept read-only.

``load(root)`` reads these files under ``root`` (the repository when omitted) and returns one
:class:`Tables`:

=====================================  ============================================================
file                                   becomes
=====================================  ============================================================
``derived/client/basedata.json``       ``basedata[(class, level)]``: ``hp mana end hp_regen end_regen
                                       hp_fac mana_fac end_fac``, as the client prints them
``derived/client/acmitigation.json``   ``softcap[(class, level)]``: ``(cap, rate past the cap)``
``derived/client/skillcaps.json``      ``skillcap[(class, skill name, level)]``: the cap, for the
                                       skills the client file names (the others are left out)
``derived/client/zones.json``          ``zones[id]``: ``name c3 c4 flagged``
``rules/races.json``                   ``races``: the dict of :func:`trioforge.data.races.load`
``rules/rules.json``                   ``rules``: a :class:`trioforge.rules.Rules`
=====================================  ============================================================

A class is its three-letter code (``"PAL"``), never its number. Numbers stay as the files give them
(whole numbers or floats); the evaluator turns a float into the exact decimal it was written as.

Reading **fails closed**: a missing or damaged table, a duplicate key, a class outside 1 to 16, a negative
number, a number of the wrong kind or an unexpected column raises :class:`TablesError`, which lists every
problem found. The mappings are read-only (``types.MappingProxyType``), so the tables cannot be changed
by accident while a solve runs.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from trioforge import rules as rules_module
from trioforge.classes import CLASS_CODES
from trioforge.data import races as races_module

__all__ = ["REPO", "Tables", "TablesError", "load"]

# pipeline/trioforge/model/tables.py -> the repository root is three folders up.
REPO = Path(__file__).resolve().parents[3]

MAX_LEVEL = 130  # the client's files list levels up to this; the derived files keep fewer

BASEDATA_FIELDS = ("hp", "mana", "end", "hp_regen", "end_regen", "hp_fac", "mana_fac", "end_fac")


class TablesError(ValueError):
    """A table file is missing or damaged. ``problems`` lists every defect found."""

    def __init__(self, problems: list[str], source: str = "<memory>") -> None:
        self.problems = list(problems)
        self.source = source
        count = len(self.problems)
        head = f"invalid model tables under {source}: {count} problem{'s' if count != 1 else ''}"
        super().__init__("\n".join([head, *(f"  - {problem}" for problem in self.problems)]))


@dataclass(frozen=True)
class Tables:
    """Everything the model looks up. All mappings are read-only."""

    basedata: Mapping[tuple[str, int], Mapping[str, float]]
    softcap: Mapping[tuple[str, int], tuple[int, float]]
    skillcap: Mapping[tuple[str, str, int], int]
    zones: Mapping[int, Mapping[str, Any]]
    races: dict[str, Any]
    rules: rules_module.Rules


# ---- reading -------------------------------------------------------------------------------


def load(root: str | os.PathLike[str] = REPO) -> Tables:
    """Read the tables under ``root`` (the repository by default). See the module docstring."""
    base = Path(root)
    problems: list[str] = []
    client = base / "derived" / "client"
    basedata = _basedata(_read(client / "basedata.json", "rows", problems), problems)
    softcap = _softcap(_read(client / "acmitigation.json", "rows", problems), problems)
    skillcap = _skillcap(_read(client / "skillcaps.json", "rows", problems, extra="skill_names"), problems)
    zones = _zones(_read(client / "zones.json", "zones", problems), problems)
    if problems:
        raise TablesError(problems, str(base))
    races = races_module.load(base / "rules" / "races.json")
    rules = rules_module.load(base / "rules" / "rules.json")
    return Tables(
        basedata=MappingProxyType(basedata),
        softcap=MappingProxyType(softcap),
        skillcap=MappingProxyType(skillcap),
        zones=MappingProxyType(zones),
        races=races,
        rules=rules,
    )


def _read(path: Path, rows_key: str, problems: list[str], extra: str | None = None):
    """``(file name, rows, the object under key extra or None)`` for a good file, else None after recording why not."""
    name = f"{path.parent.name}/{path.name}" if path.parent.name else path.name
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        problems.append(f"{name}: file is missing")
        return None
    except (OSError, UnicodeDecodeError) as exc:
        problems.append(f"{name}: cannot be read ({type(exc).__name__})")
        return None
    try:
        data = json.loads(text, parse_constant=_no_constant)
    except (ValueError, RecursionError) as exc:
        problems.append(f"{name}: not valid JSON ({type(exc).__name__})")
        return None
    if not isinstance(data, dict):
        problems.append(f"{name}: must hold one JSON object")
        return None
    rows = data.get(rows_key)
    if not isinstance(rows, list):
        problems.append(f"{name}: '{rows_key}' must be a list of rows")
        return None
    if not rows:
        problems.append(f"{name}: no rows")
        return None
    names = None
    if extra is not None:
        names = data.get(extra)
        if not isinstance(names, dict):
            problems.append(f"{name}: '{extra}' must be an object")
            return None
    return name, rows, names


def _no_constant(name: str):
    raise ValueError(f"{name} is not a JSON number")


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _row_problems(name: str, number: int, row: Any, fields: Mapping[str, str]) -> list[str]:
    """Defects of one row against ``{field: kind}``.

    The kinds are 'class', 'level', 'int', 'cap', 'rate', 'number', 'bool' and 'text'.
    """
    where = f"{name} row {number}"
    if not isinstance(row, dict):
        return [f"{where}: must be an object"]
    problems = [f"{where}: unexpected column {key!r}" for key in sorted(set(row) - set(fields))]
    for field, kind in fields.items():
        if field not in row:
            problems.append(f"{where}: missing column {field!r}")
            continue
        value = row[field]
        if kind == "class":
            ok = _is_int(value) and 1 <= value <= len(CLASS_CODES)
            hint = f"must be a whole number from 1 to {len(CLASS_CODES)}"
        elif kind == "level":
            ok = _is_int(value) and 1 <= value <= MAX_LEVEL
            hint = f"must be a whole number from 1 to {MAX_LEVEL}"
        elif kind == "int":
            ok = _is_int(value) and value >= 0
            hint = "must be a whole number of at least 0"
        elif kind == "cap":
            ok = _is_number(value) and value > 0
            hint = "must be a number above 0"
        elif kind == "rate":
            ok = _is_number(value) and 0 <= value <= 1
            hint = "must be a number from 0 to 1"
        elif kind == "number":
            ok = _is_number(value) and value >= 0
            hint = "must be a number of at least 0"
        elif kind == "bool":
            ok = type(value) is bool
            hint = "must be true or false"
        else:  # text
            ok = isinstance(value, str) and bool(value.strip())
            hint = "must be non-blank text"
        if not ok:
            problems.append(f"{where}: {field} {hint}")
    return problems


def _table(source, fields: Mapping[str, str], key_fields: tuple[str, ...], problems: list[str]):
    """The valid rows of one table as ``(key tuple, row)``; defects and duplicate keys go to ``problems``."""
    if source is None:
        return []
    name, rows, _ = source
    seen: dict[tuple, int] = {}
    kept = []
    for number, row in enumerate(rows):
        found = _row_problems(name, number, row, fields)
        if found:
            problems.extend(found)
            continue
        key = tuple(row[field] for field in key_fields)
        if key in seen:
            problems.append(f"{name} row {number}: duplicate key {key} (first at row {seen[key]})")
            continue
        seen[key] = number
        kept.append((key, row))
    return kept


def _basedata(source, problems: list[str]) -> dict:
    fields = {"class": "class", "level": "level", **{field: "number" for field in BASEDATA_FIELDS}}
    return {
        (CLASS_CODES[key[0] - 1], key[1]): MappingProxyType({field: row[field] for field in BASEDATA_FIELDS})
        for key, row in _table(source, fields, ("class", "level"), problems)
    }


def _softcap(source, problems: list[str]) -> dict:
    fields = {"class": "class", "level": "level", "ac_cap": "cap", "past_cap_rate": "rate"}
    return {
        (CLASS_CODES[key[0] - 1], key[1]): (row["ac_cap"], row["past_cap_rate"])
        for key, row in _table(source, fields, ("class", "level"), problems)
    }


def _skillcap(source, problems: list[str]) -> dict:
    if source is None:
        return {}
    name, rows, names = source
    skill_names: dict[int, str] = {}
    for key, value in names.items():
        if not (isinstance(key, str) and key.isdigit() and isinstance(value, str) and value.strip()):
            problems.append(f"{name}: skill_names must map a skill number to its name")
            return {}
        skill_names[int(key)] = value
    fields = {"class": "class", "skill": "int", "level": "level", "cap": "int"}
    table = _table(source, fields, ("class", "skill", "level"), problems)
    return {
        (CLASS_CODES[key[0] - 1], skill_names[key[1]], key[2]): row["cap"]
        for key, row in table
        if key[1] in skill_names  # a skill the client file does not name is of no use to the planner
    }


def _zones(source, problems: list[str]) -> dict:
    fields = {"id": "int", "name": "text", "c3": "int", "c4": "int", "flagged": "bool"}
    return {
        key[0]: MappingProxyType({field: row[field] for field in ("name", "c3", "c4", "flagged")})
        for key, row in _table(source, fields, ("id",), problems)
    }
