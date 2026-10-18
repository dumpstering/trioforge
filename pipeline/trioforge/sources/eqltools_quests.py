"""Quest givers from EQL Tools' quest JSON, reduced to what the evidence ladder reads.

EQL Tools (https://eqltools.com) publishes a quest JSON compiled from eqlwiki, declared CC BY-SA 4.0
(its code is not licensed and is never used here). A copy sits in ``sources/eqltools/`` (git-ignored);
this module reads it and writes ``derived/quests.json``::

    python -m trioforge.sources.eqltools_quests --in sources/eqltools/quest-items-2026-10-11.json --out derived/quests.json

``quests.json`` is ``{"provenance", "license", "attribution", "quests": [...]}`` and each quest is
``{"title", "wiki_title", "giver", "zone", "era", "rewards", "wants"}``:

* ``title`` is the quest's name and ``wiki_title`` its wiki page title when that names it differently;
* ``giver`` is the NPC who gives the quest and ``zone`` the zone that NPC stands in (null when the
  source does not say), as EQL Tools spells them: the evidence ladder maps the zone to a client zone;
* ``era`` is the wiki page's era tag written as the page parser writes it (``Kunark Era``), or null;
* ``rewards`` are the items the quest gives and ``wants`` the items it takes on hand-in.

Every string is passed through the catalog's ``sanitize_text``: the source is wiki text, which is hostile
input. A file that does not declare the licence CC BY-SA 4.0 is refused. The output is written all or
nothing; an error leaves any old file as it was and ends the command with exit status 2.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import trioforge
from trioforge.data.evidence import normalize_era
from trioforge.data.jsonio import JsonFileError, load_strict, render
from trioforge.data.normalize import sanitize_text
from trioforge.sources.client_tables import commit_files, iso_date, one_line, today_utc

__all__ = ["ATTRIBUTION", "GENERATOR", "INPUT_LICENSE", "main", "read_quests", "write_quests"]

INPUT_LICENSE = "CC BY-SA 4.0"
GENERATOR = f"trioforge.sources.eqltools_quests {trioforge.__version__}"
ATTRIBUTION = (
    "Quest giver data compiled by EQL Tools (https://eqltools.com/sources) from eqlwiki (https://eqlwiki.com/), "
    "licensed CC BY-SA 4.0; changes: reduced to quest title, giver, giver zone, era tag, rewards and items handed in, "
    "strings sanitized."
)
MINIMUM_QUESTS = 100  # the real file has 930; fewer means a different or cut-short file
MAX_NAMES = 200  # rewards or wants kept per quest

_DATE_IN_NAME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})")


def _clean(value: Any) -> str | None:
    """Sanitized text, or None for anything that is not text or is empty once sanitized."""
    if not isinstance(value, str):
        return None
    return sanitize_text(value) or None


def _names(values: Any, *, pairs: bool = False) -> list[str]:
    """Sanitized, distinct, non-empty names in order; with ``pairs`` each value is ``[name, count]``."""
    found: list[str] = []
    if not isinstance(values, list):
        return found
    for value in values:
        if pairs:
            value = value[0] if isinstance(value, (list, tuple)) and value else None
        name = _clean(value)
        if name and name not in found:
            found.append(name)
        if len(found) >= MAX_NAMES:
            break
    return found


def _era(value: Any) -> str | None:
    text = _clean(value)
    if not text or not text.casefold().endswith(" era"):
        return None
    return normalize_era(text)


def read_quests(path: str | Path, *, minimum: int = MINIMUM_QUESTS) -> dict[str, Any]:
    """The reduced quests of one EQL Tools quest JSON: ``{"quests": [...], "skipped": n}``.

    Raises :class:`ValueError` (a one-line message, no file content) if the file is not strict JSON, does
    not declare the licence CC BY-SA 4.0, or holds fewer than ``minimum`` (:data:`MINIMUM_QUESTS`) quests.
    """
    source = Path(path)
    try:
        data = load_strict(source)
    except JsonFileError as error:
        raise ValueError(str(error)) from error
    meta = data.get("meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict) or meta.get("license") != INPUT_LICENSE:
        raise ValueError(f"{source.name}: the file does not declare the licence {INPUT_LICENSE}; it is not used")
    raw = data.get("quests")
    if not isinstance(raw, list):
        raise ValueError(f"{source.name}: no list of quests")
    quests: list[dict[str, Any]] = []
    skipped = 0
    for entry in raw:
        title = _clean(entry.get("n")) if isinstance(entry, dict) else None
        if title is None:
            skipped += 1
            continue
        page = _clean(entry["t"].replace("_", " ")) if isinstance(entry.get("t"), str) else None
        quests.append(
            {
                "title": title,
                "wiki_title": page if page and page.casefold() != title.casefold() else None,
                "giver": _clean(entry.get("giver")),
                "zone": _clean(entry.get("zone")),
                "era": _era(entry.get("era")),
                "rewards": _names(entry.get("rewards")),
                "wants": _names(entry.get("want"), pairs=True),
            }
        )
    if len(quests) < minimum:
        raise ValueError(f"{source.name}: only {len(quests)} usable quests, fewer than the {minimum} a whole file has")
    quests.sort(key=lambda quest: (quest["title"].casefold(), quest["title"]))
    return {"quests": quests, "skipped": skipped}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _input_date(path: Path) -> str:
    """The date in the file's name (``quest-items-2026-10-11.json``), else the UTC date it was last written."""
    found = _DATE_IN_NAME.search(path.name)
    if found:
        try:
            datetime.date.fromisoformat(found.group(1))
            return found.group(1)
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc).date().isoformat()


def write_quests(
    source: str | Path, out: str | Path, generated: str, *, input_name: str | None = None, minimum: int = MINIMUM_QUESTS
) -> dict[str, Any]:
    """Read ``source`` and write ``out`` (``derived/quests.json``) all or nothing; returns the document.

    ``input_name`` is how the input is named in the provenance (default ``sources/eqltools/<file name>``).
    """
    path = Path(source)
    reduced = read_quests(path, minimum=minimum)
    document = {
        "provenance": {
            "inputs": [
                {
                    "file": input_name or f"sources/eqltools/{path.name}",
                    "sha256": _sha256(path),
                    "date": _input_date(path),
                }
            ],
            "generator": GENERATOR,
            "generated": generated,
        },
        "license": INPUT_LICENSE,
        "attribution": ATTRIBUTION,
        "quests": reduced["quests"],
    }
    target = Path(out)
    commit_files(target.parent, {target.name: render(document, per_line=("quests",))}, last=target.name)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.sources.eqltools_quests",
        description="Reduce EQL Tools' quest JSON to derived/quests.json (quest title, giver, giver zone, era).",
    )
    parser.add_argument("--in", dest="source", required=True, type=Path, help="EQL Tools quest JSON (sources/eqltools/...)")
    parser.add_argument("--out", type=Path, default=Path("derived/quests.json"), help="output file")
    parser.add_argument("--date", type=iso_date, help="generation date, YYYY-MM-DD (default: today in UTC)")
    args = parser.parse_args(argv)
    try:
        document = write_quests(args.source, args.out, args.date or today_utc())
    except (OSError, ValueError) as error:
        print(f"error: {one_line(error)}", file=sys.stderr)
        return 2
    quests = document["quests"]
    print(
        f"{args.out.name}: {len(quests)} quests, {sum(1 for q in quests if q['zone'])} with a giver zone, "
        f"{sum(1 for q in quests if q['era'])} with an era tag"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
