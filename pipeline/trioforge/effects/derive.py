"""The spells the effects layer reads, as a derived file (``derived/client/effect-spells.json``).

The release build works from committed public data, as it does for ``spells-l50.json``; this file is the other half of the client's spell file that the
effects layer needs: not only the beneficial buffs that :mod:`trioforge.sources.client_spells` keeps, but every spell a class can cast up to the level cap
(the layer measures what a class casts, to see which focus touches how much of it) and every spell that has the name of an effect on a wiki item (the
clicks, procs, worn effects and foci of the catalog, whose spell is found by name).

It reads ``spells_us.txt`` the way :mod:`~trioforge.sources.client_spells` does: the same file reader and row checks, the same ``^`` columns, the same effect
slots out of the last column (:func:`trioforge.sources.client_spells._effect_groups`) and the same duration and value formulas, which are applied later, at
the level an effect is cast at. The columns it adds to those the other module documents (0-based) are::

    8 cast time in ms    14 mana cost    29 resist type (1 magic, 2 fire, 3 cold, 4 poison, 5 disease)
    32 skill (41 singing, 12 brass, 49 stringed, 54 wind, 70 percussion for a bard song; the instrument foci limit themselves to one of these)

A row of the file is ``{"id", "name", "cast_ms", "mana", "dur": [formula, cap], "ben", "res", "tgt", "sk", "lv": {class: level}, "fx": [[slot, spa, base, limit, formula, max]]}``
with ``lv`` holding every class that can use the spell (level below 255), whatever the level. Rows are sorted by id. A row keeps its ``name`` only when an item effect of
the wiki calls the spell by it (the layer finds those spells by name); the other rows, the class spells that only say what a class casts, have the name ``""``: nothing reads
it, and a spell name is a game word that the privacy scan of the repository may read as a private name.

The command line writes the file and adds it to ``manifest.json`` (the manifest keeps the input it was made from, which is the same ``spells_us.txt`` as that of
``spells-l50.json``)::

    python -m trioforge.effects.derive --client-dir DIR --out derived/client [--catalog derived/catalog.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import trioforge
from trioforge.classes import CLASS_CODES
from trioforge.sources import client_spells as cs
from trioforge.sources import client_tables as tables

__all__ = ["CAP", "FILE", "GENERATOR", "effect_names", "generate", "main", "read_rows"]

FILE = "effect-spells.json"
GENERATOR = f"trioforge.effects.derive {trioforge.__version__}"
CAP = 50  # the level cap: a spell is kept when some class gets it at or below this level
CAST_MS, MANA, RESIST, SKILL = 8, 14, 29, 32  # 0-based columns the other reader does not use
#: spell names on the wiki that the client spells under another name
ALIASES = {"Complete Healing": "Complete Heal", "Invisibility versus Animal": "Invisibility versus Animals"}


def effect_names(catalog: dict[str, Any]) -> set[str]:
    """The spell names of the effects of the wiki-level items of a catalog document (aliases applied)."""
    names: set[str] = set()
    for item in catalog["items"]:
        if item["evidence"]["level"] == "wiki":
            names.update(ALIASES.get(effect["name"], effect["name"]) for effect in item["effects"])
    return names


def _whole(text: str) -> int:
    """A whole number from a column that may hold a decimal (some unused rows do)."""
    return int(float(text)) if text else 0


def read_rows(path: str | Path, names: Iterable[str], *, cap: int = CAP) -> list[dict[str, Any]]:
    """The spells of ``spells_us.txt`` that a class gets at ``cap`` or below, or that are called one of ``names``, sorted by id.

    The file is held to the checks of :mod:`trioforge.sources.client_spells`: a row that is not a spell, has too few columns or a width unlike the first row's,
    a repeated id, or no effect slots anywhere in the file is refused, naming the line."""
    wanted = set(names)
    source = Path(path)
    rows: list[dict[str, Any]] = []
    first_line: dict[int, int] = {}
    count = with_effects = 0
    width = None
    for number, text in tables.read_lines(source):
        if not text.strip() or text.startswith("#"):
            continue
        fields = text.split("^")
        if cs._SPELL_ID.fullmatch(fields[cs.ID]) is None:
            raise tables.problem(source, number, "the first column is not a spell id")
        if len(fields) < cs.MIN_FIELDS:
            raise tables.problem(source, number, f"expected at least {cs.MIN_FIELDS} columns, found {len(fields)}")
        if width is None:
            width = len(fields)
        elif len(fields) != width:
            raise tables.problem(source, number, f"expected {width} columns like the first row, found {len(fields)}")
        tables.remember(source, number, first_line, int(fields[cs.ID]), "spell id")
        count += 1
        if "|" in fields[-1]:
            with_effects += 1
        levels = {}
        for position, code in enumerate(CLASS_CODES):
            at = tables.whole(source, number, fields[cs.FIRST_CLASS_LEVEL + position], f"{code} level", high=cs.LARGEST_CLASS_LEVEL)
            if 0 < at < cs.LARGEST_CLASS_LEVEL:
                levels[code] = at
        if not (levels and min(levels.values()) <= cap) and fields[cs.NAME] not in wanted:
            continue
        rows.append(
            {
                "id": int(fields[cs.ID]),
                "name": fields[cs.NAME] if fields[cs.NAME] in wanted else "",
                "cast_ms": _whole(fields[CAST_MS]),
                "mana": _whole(fields[MANA]),
                "dur": [_whole(fields[cs.DURATION_FORMULA]), _whole(fields[cs.DURATION_CAP])],
                "ben": _whole(fields[cs.BENEFICIAL]),
                "res": _whole(fields[RESIST]),
                "tgt": _whole(fields[cs.TARGET]),
                "sk": _whole(fields[SKILL]),
                "lv": levels,
                "fx": [list(group) for group in cs._effect_groups(source, number, fields[-1])],
            }
        )
    tables.enough_rows(source, count)
    if count >= 100 and with_effects == 0:
        raise ValueError(f"{source.name}: no spell row has effect slots in its last column; has the layout changed?")
    rows.sort(key=lambda row: row["id"])
    return rows


def generate(client_dir: str | Path, out_dir: str | Path, catalog: str | Path, generated: str) -> str:
    """Read ``spells_us.txt`` and the effect names of the catalog, write ``effect-spells.json`` and update the manifest, all or nothing."""
    root = Path(client_dir)
    if not (root / cs.SPELLS_FILE).is_file():
        raise tables.MissingInput(f"missing input file: {cs.SPELLS_FILE}")
    document = json.loads(Path(catalog).read_text(encoding="utf-8"))
    names = effect_names(document)
    out = Path(out_dir)
    known = tables.read_manifest(out)
    record, rows = tables.read_checked(root, cs.SPELLS_FILE, lambda path: read_rows(path, names))
    earlier = known[0].get(cs.SPELLS_FILE)
    if earlier is not None and earlier["sha256"] == record["sha256"]:
        record = earlier  # the same file again (a copy of it has a date of its own): the manifest keeps the date it has
    floor = tables.MINIMUM_ROWS["spells"]
    if len(rows) < floor:
        raise ValueError(f"{cs.SPELLS_FILE}: only {len(rows)} spells for the effects layer, fewer than the {floor} a whole file has")
    texts = {
        FILE: tables.render_json({"provenance": tables.provenance([record], generated, GENERATOR), "cap": CAP, "spells": rows}),
    }
    outputs = [{"file": FILE, "inputs": [cs.SPELLS_FILE], "generated": generated}]
    texts[tables.MANIFEST_FILE] = tables.render_json(tables.merge_manifest(known, [record], outputs, generated))
    tables.commit_files(out, texts)
    return f"{FILE}: {len(rows)} spells"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.effects.derive",
        description="Write the spells the effects layer reads (every class spell to the cap, and the spells the wiki's item effects name) as derived JSON.",
    )
    parser.add_argument("--client-dir", type=Path, help=f"install folder (default: ${tables.ENV_CLIENT_DIR}, else the stock folder under %%PUBLIC%%)")
    parser.add_argument("--out", type=Path, default=Path("derived/client"), help="output folder")
    parser.add_argument("--catalog", type=Path, default=Path("derived/catalog.json"), help="the public catalog")
    parser.add_argument("--date", type=tables.iso_date, help="generation date, YYYY-MM-DD (default: today in UTC)")
    args = parser.parse_args(argv)
    client_dir = tables.resolve_client_dir(args.client_dir)
    if client_dir is None:
        print(f"error: no client folder: pass --client-dir or set {tables.ENV_CLIENT_DIR}", file=sys.stderr)
        return 2
    try:
        print(generate(client_dir, args.out, args.catalog, args.date or tables.today_utc()))
    except (OSError, ValueError) as exc:
        print(f"error: {tables.one_line(exc)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
