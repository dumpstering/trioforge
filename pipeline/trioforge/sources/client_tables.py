"""The client's text tables: zone flags, class pools, softcaps and skill caps.

Four text resources that ship with the game are read, as text and nothing else, and each
becomes one derived JSON file under ``derived/client/``:

================================  =====================  =====================================
resource                          derived file           columns (``^`` separated)
================================  =====================  =====================================
``Resources/ZoneNames.txt``       ``zones.json``         ``id^name^c3^c4``
``Resources/basedata.txt``        ``basedata.json``      ``level^class^hp^mana^end^hp_regen^``
                                                         ``end_regen^hp_fac^mana_fac^end_fac^``
``Resources/ACMitigation.txt``    ``acmitigation.json``  ``class^level^ac_cap^past_cap_rate^``
``Resources/skillcaps.txt``       ``skillcaps.json``     ``class^skill^level^cap^0^``
================================  =====================  =====================================

``basedata.txt`` lists the level first and the class second; the derived rows name both. Its
sixth and seventh columns hold one number per level, the same for every class; they are named
``hp_regen`` and ``end_regen`` after their place in the column order, and their meaning is not
checked here. A zone is *flagged* when its third column is not zero. Class ids run 1 to 16 in the
order of the class codes (WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER).

Every ``read_*`` function takes a path and returns a dict that is ready to dump to JSON. Reading
**fails closed**, so a damaged or changed file stops the run instead of quietly shrinking a table:

* Only blank lines and lines that start with ``#`` are skipped. Any other line that does not fit
  its table raises :class:`ValueError` naming the file and the line number, never the line's text.
* The file must be plain ASCII (a UTF-8 byte order mark at the start is dropped first); a byte
  above 127 is an error, in a comment too.
* A row has exactly the table's columns, plus at most one empty column after a closing ``^``.
* A repeated key (zone id; class and level; class, skill and level) is an error, and so is a value
  out of range: a class outside 1 to 16, a level outside 1 to 130, a negative number, or one too
  big to be a number.
* ``ACMitigation.txt`` must start with its header line.
* A file with no data rows is an error. The command line also refuses a table with fewer rows
  than :data:`MINIMUM_ROWS`, which a file that was cut short would have.

**Scope.** ``basedata``, ``acmitigation`` and ``skillcaps`` keep only levels 1 to
:data:`MAX_TABLE_LEVEL` (60), which cover the planner's levels 50 and 55 with margin; only the
numbers the planner uses are published. Every row is checked first, so a damaged row above the
limit still stops the run. Zones keep all their rows, with id, name, ``c3``, ``c4`` and ``flagged``,
because the zone names are needed for the alias map.

The command line reads the install folder (``--client-dir``, else the environment variable
``TRIOFORGE_EQL_DIR``, else the stock folder under ``%PUBLIC%``) and writes the four files plus
``manifest.json``::

    python -m trioforge.sources.client_tables --client-dir DIR --out derived/client

It reads and checks everything, and makes every text, before it writes anything. The old manifest
must be readable and valid; a failure anywhere leaves the output folder exactly as it was. The files are
written next to their names as temporary files and renamed into place, the manifest last. Any
``OSError`` or ``ValueError`` ends the run with exit status 2 and a one-line message.

Each derived file carries ``provenance``: the resource's name relative to the install folder, the
sha256 of its bytes and the date it was last written (the patch date), the generator and the
generation date. Dates are UTC calendar dates; the sha256 is what identifies a file. No local path
is ever written, and the game files themselves are never copied.
"""

import argparse
import datetime
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import trioforge
from trioforge.classes import CLASS_CODES

__all__ = [
    "ACMITIGATION_FILE",
    "ACMITIGATION_HEADER",
    "BASEDATA_FILE",
    "ENV_CLIENT_DIR",
    "GENERATOR",
    "INPUT_FILES",
    "MANIFEST_FILE",
    "MAX_FILE_LEVEL",
    "MAX_TABLE_LEVEL",
    "MINIMUM_ROWS",
    "SKILLCAPS_FILE",
    "SKILL_NAMES",
    "ZONES_FILE",
    "MissingInput",
    "commit_files",
    "data_rows",
    "decimal",
    "enough_rows",
    "exact_columns",
    "generate",
    "input_record",
    "iso_date",
    "main",
    "merge_manifest",
    "one_line",
    "problem",
    "provenance",
    "read_acmitigation",
    "read_basedata",
    "read_checked",
    "read_lines",
    "read_manifest",
    "read_skillcaps",
    "read_zones",
    "remember",
    "render_json",
    "resolve_client_dir",
    "today_utc",
    "update_manifest",
    "utc_date",
    "whole",
    "write_json",
]

ENV_CLIENT_DIR = "TRIOFORGE_EQL_DIR"

ZONES_FILE = "Resources/ZoneNames.txt"
BASEDATA_FILE = "Resources/basedata.txt"
ACMITIGATION_FILE = "Resources/ACMitigation.txt"
SKILLCAPS_FILE = "Resources/skillcaps.txt"
INPUT_FILES = (ZONES_FILE, BASEDATA_FILE, ACMITIGATION_FILE, SKILLCAPS_FILE)

MANIFEST_FILE = "manifest.json"
GENERATOR = f"trioforge.sources.client_tables {trioforge.__version__}"

# The derived tables keep the levels 1 to 60: only the numbers the planner uses are published, and levels
# 50 and 55 are covered with margin. The client's files list levels up to 130; a row beyond that is a
# damaged row.
MAX_TABLE_LEVEL = 60
MAX_FILE_LEVEL = 130

# The fewest data rows a whole input has; the command line refuses less as damaged or cut short. The real
# files hold 701 zones, 2080 basedata rows, 2080 softcap rows and 80915 skill-cap rows. For spells the
# number counts the beneficial spells kept at each level, not the rows of the file.
MINIMUM_ROWS = {"zones": 600, "basedata": 1000, "acmitigation": 1000, "skillcaps": 10000, "spells": 200}

# The first line of ACMitigation.txt, without its closing caret.
ACMITIGATION_HEADER = "#CLASS^LVL^AC_CAP^SOFT_CAP_MULTIPLIER"

# Skill id -> name for the skills the planner uses (the standard numbering of the game's skill
# list). The file holds other skill ids too; their rows are kept and simply have no name here.
SKILL_NAMES: dict[int, str] = {
    0: "1H Blunt",
    1: "1H Slashing",
    2: "2H Blunt",
    3: "2H Slashing",
    4: "Abjuration",
    5: "Alteration",
    7: "Archery",
    8: "Backstab",
    10: "Bash",
    11: "Block",
    13: "Channeling",
    14: "Conjuration",
    15: "Defense",
    18: "Divination",
    19: "Dodge",
    20: "Double Attack",
    22: "Dual Wield",
    24: "Evocation",
    28: "Hand to Hand",
    30: "Kick",
    31: "Meditate",
    33: "Offense",
    34: "Parry",
    36: "1H Piercing",
    37: "Riposte",
    51: "Throwing",
    71: "Intimidation",
    73: "Taunt",
    76: "Triple Attack",
    77: "2H Piercing",
}

_BYTE_ORDER_MARK = b"\xef\xbb\xbf"
_WHOLE_NUMBER = re.compile(r"-?[0-9]+")
_DECIMAL = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LONGEST_NUMBER = 40  # digits; anything longer is not a number the client's tables hold


class MissingInput(FileNotFoundError):
    """One or more of the client's text resources is not in the install folder."""


# ---- reading --------------------------------------------------------------------------------


def problem(path: str | os.PathLike[str], number: int, what: str) -> ValueError:
    """A :class:`ValueError` naming the file and the line number; never the text of the line."""
    return ValueError(f"{Path(path).name}: line {number}: {what}")


def read_lines(path: str | os.PathLike[str]) -> Iterator[tuple[int, str]]:
    """Yield ``(line number, text)`` for each line of a plain ASCII file, line end removed.

    A UTF-8 byte order mark at the start is dropped. Lines are split on ``\\n`` only
    (``str.splitlines`` would also break on control characters that can sit inside a name) and a
    ``\\r`` before it is dropped. A byte above 127 raises :class:`ValueError` naming the line
    (never the byte): the files are ASCII, so anything else means a different file.
    """
    source = Path(path)
    data = source.read_bytes()
    stream = io.BytesIO(data)
    if data.startswith(_BYTE_ORDER_MARK):
        stream.seek(len(_BYTE_ORDER_MARK))
    for number, raw in enumerate(stream, start=1):
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            raise problem(source, number, "not plain ASCII") from None
        yield number, text.rstrip("\n").rstrip("\r")


def data_rows(path: str | os.PathLike[str]) -> Iterator[tuple[int, list[str]]]:
    """Yield ``(line number, fields)`` for each data line: blank lines and ``#`` lines are skipped
    and nothing else is."""
    for number, text in read_lines(path):
        if not text.strip() or text.startswith("#"):
            continue
        yield number, text.split("^")


def whole(
    path: str | os.PathLike[str], number: int, field: str, name: str, low: int = 0, high: int | None = None
) -> int:
    """A whole number from ``low`` (not negative unless said so) up to ``high`` (no limit if ``None``)."""
    if _WHOLE_NUMBER.fullmatch(field) is None:
        raise problem(path, number, f"{name} is not a whole number")
    if len(field) > _LONGEST_NUMBER:
        raise problem(path, number, f"{name} is out of range")
    value = int(field)
    if value < low or (high is not None and value > high):
        raise problem(path, number, f"{name} is out of range")
    return value


def decimal(path: str | os.PathLike[str], number: int, field: str, name: str) -> float:
    """A finite number that is not negative, written with or without a decimal point."""
    if _DECIMAL.fullmatch(field) is None:
        raise problem(path, number, f"{name} is not a number")
    value = float(field)
    if not math.isfinite(value) or value < 0:
        raise problem(path, number, f"{name} is out of range")
    return value


def exact_columns(
    path: str | os.PathLike[str], number: int, fields: list[str], count: int, closing_caret: bool = False
) -> list[str]:
    """The first ``count`` fields of a row that has exactly ``count`` columns; with ``closing_caret``
    one more, empty column (the text after a ``^`` that ends the row) is allowed too."""
    if closing_caret and len(fields) == count + 1 and fields[count] == "":
        return fields[:count]
    if len(fields) != count:
        raise problem(path, number, f"expected {count} columns, found {len(fields)}")
    return fields


def remember(path: str | os.PathLike[str], number: int, seen: dict[Any, int], key: Any, what: str) -> None:
    """Note the line of a row's key; a key met before is an error naming both lines."""
    if key in seen:
        raise problem(path, number, f"duplicate {what} (first on line {seen[key]})")
    seen[key] = number


def enough_rows(path: str | os.PathLike[str], count: int, minimum_rows: int = 1) -> None:
    """Raise :class:`ValueError` when a file had no data rows, or fewer than ``minimum_rows``."""
    name = Path(path).name
    if count == 0:
        raise ValueError(f"{name}: no data rows")
    if count < minimum_rows:
        raise ValueError(f"{name}: only {count} data rows, fewer than the {minimum_rows} a whole file has")


def read_zones(path: str | os.PathLike[str], *, minimum_rows: int = 1) -> dict[str, Any]:
    """``id^name^c3^c4`` lines -> ``{"flagged_count", "zones": [{id, name, c3, c4, flagged}]}``.

    A zone is flagged when ``c3`` is not zero. Every row is kept, whatever its id.
    """
    zones = []
    seen: dict[int, int] = {}
    for number, fields in data_rows(path):
        fields = exact_columns(path, number, fields, 4)
        zone_id = whole(path, number, fields[0], "id")
        c3 = whole(path, number, fields[2], "c3")
        c4 = whole(path, number, fields[3], "c4")
        remember(path, number, seen, zone_id, "zone id")
        zones.append({"id": zone_id, "name": fields[1], "c3": c3, "c4": c4, "flagged": c3 != 0})
    enough_rows(path, len(zones), minimum_rows)
    return {"flagged_count": sum(1 for zone in zones if zone["flagged"]), "zones": zones}


_BASEDATA_POOLS = ("hp", "mana", "end", "hp_regen", "end_regen", "hp_fac", "mana_fac", "end_fac")


def read_basedata(
    path: str | os.PathLike[str], *, max_level: int = MAX_TABLE_LEVEL, minimum_rows: int = 1
) -> dict[str, Any]:
    """``level^class^hp^mana^end^hp_regen^end_regen^hp_fac^mana_fac^end_fac^`` -> ``{"rows": [...]}``.

    Each row is ``{"class", "level", "hp", "mana", "end", "hp_regen", "end_regen", "hp_fac",
    "mana_fac", "end_fac"}``: class and level are integers and the eight pool numbers floats. A
    trailing ``^`` is allowed. Only levels up to ``max_level`` are kept, after every row has been
    checked; ``minimum_rows`` counts the rows read.
    """
    rows = []
    seen: dict[tuple[int, int], int] = {}
    count = 0
    for number, fields in data_rows(path):
        fields = exact_columns(path, number, fields, 2 + len(_BASEDATA_POOLS), closing_caret=True)
        level = whole(path, number, fields[0], "level", low=1, high=MAX_FILE_LEVEL)
        klass = whole(path, number, fields[1], "class", low=1, high=len(CLASS_CODES))
        row: dict[str, Any] = {"class": klass, "level": level}
        for position, name in enumerate(_BASEDATA_POOLS, start=2):
            row[name] = decimal(path, number, fields[position], name)
        remember(path, number, seen, (klass, level), "class and level")
        count += 1
        if level <= max_level:
            rows.append(row)
    enough_rows(path, count, minimum_rows)
    return {"rows": rows}


def read_acmitigation(
    path: str | os.PathLike[str], *, max_level: int = MAX_TABLE_LEVEL, minimum_rows: int = 1
) -> dict[str, Any]:
    """``class^level^ac_cap^past_cap_rate^`` -> ``{"rows": [{class, level, ac_cap, past_cap_rate}]}``.

    The file starts with its header line (:data:`ACMITIGATION_HEADER`), which is checked. ``ac_cap`` is
    the softcap of that class and level; ``past_cap_rate`` is the file's multiplier column, which the
    planner reads as the share of each point past the cap that still counts. Only levels up to
    ``max_level`` are kept, after every row has been checked; ``minimum_rows`` counts the rows read.
    """
    rows = []
    seen: dict[tuple[int, int], int] = {}
    count = 0
    header_read = False
    for number, text in read_lines(path):
        if not text.strip():
            continue
        if not header_read:
            if text not in (ACMITIGATION_HEADER, ACMITIGATION_HEADER + "^"):
                raise problem(path, number, "the first line is not the ACMitigation header")
            header_read = True
            continue
        if text.startswith("#"):
            continue
        fields = exact_columns(path, number, text.split("^"), 4, closing_caret=True)
        klass = whole(path, number, fields[0], "class", low=1, high=len(CLASS_CODES))
        level = whole(path, number, fields[1], "level", low=1, high=MAX_FILE_LEVEL)
        row = {
            "class": klass,
            "level": level,
            "ac_cap": whole(path, number, fields[2], "ac_cap"),
            "past_cap_rate": decimal(path, number, fields[3], "past_cap_rate"),
        }
        remember(path, number, seen, (klass, level), "class and level")
        count += 1
        if level <= max_level:
            rows.append(row)
    enough_rows(path, count, minimum_rows)
    return {"rows": rows}


def read_skillcaps(
    path: str | os.PathLike[str], *, max_level: int = MAX_TABLE_LEVEL, minimum_rows: int = 1
) -> dict[str, Any]:
    """``class^skill^level^cap^0^`` -> ``{"skill_names": {id: name}, "rows": [{class, skill, level, cap}]}``.

    The fifth column is always 0 in the client's file and is not kept (it must still be a whole
    number). ``skill_names`` is :data:`SKILL_NAMES` keyed by the id as text (JSON keys are text). Only
    levels up to ``max_level`` are kept, after every row has been checked; ``minimum_rows`` counts the
    rows read.
    """
    rows = []
    seen: dict[tuple[int, int, int], int] = {}
    count = 0
    for number, fields in data_rows(path):
        fields = exact_columns(path, number, fields, 5, closing_caret=True)
        klass = whole(path, number, fields[0], "class", low=1, high=len(CLASS_CODES))
        skill = whole(path, number, fields[1], "skill")
        level = whole(path, number, fields[2], "level", low=1, high=MAX_FILE_LEVEL)
        cap = whole(path, number, fields[3], "cap")
        whole(path, number, fields[4], "fifth column")
        remember(path, number, seen, (klass, skill, level), "class, skill and level")
        count += 1
        if level <= max_level:
            rows.append({"class": klass, "skill": skill, "level": level, "cap": cap})
    enough_rows(path, count, minimum_rows)
    return {"skill_names": {str(skill): name for skill, name in sorted(SKILL_NAMES.items())}, "rows": rows}


# ---- the install folder, dates and provenance -------------------------------------------------


def resolve_client_dir(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    """The install folder: ``explicit``, else ``$TRIOFORGE_EQL_DIR``, else the stock folder under
    ``%PUBLIC%``; ``None`` when none of those is set. The folder's existence is not checked."""
    if explicit is not None:
        return Path(explicit)
    from_environment = os.environ.get(ENV_CLIENT_DIR)
    if from_environment:
        return Path(from_environment)
    public = os.environ.get("PUBLIC")
    if public:
        return Path(public) / "Daybreak Game Company" / "Installed Games" / "EverQuest Legends"
    return None


def utc_date(timestamp: float) -> str:
    """The UTC calendar date, YYYY-MM-DD, of a Unix timestamp."""
    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).date().isoformat()


def today_utc(now: datetime.datetime | None = None) -> str:
    """The UTC calendar date, YYYY-MM-DD, of ``now`` (a time with a time zone) or of the present."""
    moment = datetime.datetime.now(datetime.timezone.utc) if now is None else now
    if moment.tzinfo is None:
        raise ValueError("now needs a time zone")
    return moment.astimezone(datetime.timezone.utc).date().isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def input_record(client_dir: str | os.PathLike[str], relative: str) -> dict[str, str]:
    """``{"file", "sha256", "date"}`` for one resource: its name relative to the install folder,
    the sha256 of its bytes and the UTC calendar date it was last written, which is the date of the
    patch that brought it."""
    path = Path(client_dir) / relative
    return {"file": relative, "sha256": _sha256(path), "date": utc_date(path.stat().st_mtime)}


def read_checked(
    client_dir: str | os.PathLike[str], relative: str, reader: Callable[[Path], Any]
) -> tuple[dict[str, str], Any]:
    """Run ``reader`` on one resource and return ``(input_record, what the reader returned)``.

    The resource is hashed before and after it is read. A different hash means the file changed
    under the reader (a patch landing), so nothing the reader returned can be trusted and a
    :class:`ValueError` is raised.
    """
    path = Path(client_dir) / relative
    record = input_record(client_dir, relative)
    result = reader(path)
    if _sha256(path) != record["sha256"]:
        raise ValueError(f"{relative} changed while it was being read; run again")
    return record, result


def provenance(inputs: list[dict[str, str]], generated: str, generator: str = GENERATOR) -> dict[str, Any]:
    """The ``provenance`` block of a derived file."""
    return {"inputs": inputs, "generator": generator, "generated": generated}


# ---- writing: text first, then all or nothing -------------------------------------------------


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def render_json(data: dict[str, Any]) -> str:
    """Text for a derived JSON file: one top-level key per line, and a list's items one per line.

    The output is strict JSON (no NaN or Infinity) in UTF-8 with ``\\n`` line ends, the same
    bytes for the same data, and a diff shows one changed row as one changed line.
    """
    lines = ["{"]
    last = len(data) - 1
    for position, (key, value) in enumerate(data.items()):
        if not isinstance(key, str):
            raise TypeError(f"JSON keys must be text, not {key!r}")
        comma = "," if position < last else ""
        if isinstance(value, list) and value:
            lines.append(f" {_dump(key)}: [")
            for index, item in enumerate(value):
                lines.append(f"  {_dump(item)}{',' if index < len(value) - 1 else ''}")
            lines.append(f" ]{comma}")
        else:
            lines.append(f" {_dump(key)}: {_dump(value)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _stage(folder: Path, name: str, data: bytes) -> Path:
    """Write ``data`` to a new temporary file in ``folder`` (named after ``name``) and return it."""
    handle, temp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=folder)
    temp = Path(temp_name)
    try:
        try:
            stream = os.fdopen(handle, "wb")
        except BaseException:
            os.close(handle)
            raise
        with stream:
            stream.write(data)
        os.chmod(temp, 0o644)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return temp


def _put_back(final: Path, old: bytes | None) -> bool:
    """Restore a file to ``old`` (``None``: it did not exist); False if that did not work."""
    try:
        if old is None:
            final.unlink(missing_ok=True)
        else:
            temp = _stage(final.parent, final.name, old)
            try:
                os.replace(temp, final)
            finally:
                temp.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def commit_files(out_dir: str | os.PathLike[str], rendered: Mapping[str, str], *, last: str = MANIFEST_FILE) -> None:
    """Put the texts of ``rendered`` (``{file name: text}``) into ``out_dir`` all or nothing.

    Every text is first written to a temporary file in the same folder; only when all of them are
    written are the temporary files renamed over the final names with ``os.replace``, the file named
    ``last`` (the manifest) after the others. If a rename fails, the files already replaced are put
    back as they were (a file that did not exist is removed again), every temporary file is removed and the
    error is raised, so an error leaves the folder as it was found. Only a failure to put a file
    back can leave a mix, and it is reported with the names.
    """
    folder = Path(out_dir)
    names = [name for name in rendered if name != last] + ([last] if last in rendered else [])
    folder.mkdir(parents=True, exist_ok=True)
    staged: dict[str, Path] = {}
    try:
        for name in names:
            staged[name] = _stage(folder, name, rendered[name].encode("utf-8"))
        before = {name: (folder / name).read_bytes() if (folder / name).is_file() else None for name in names}
        done: list[str] = []
        try:
            for name in names:
                os.replace(staged[name], folder / name)
                done.append(name)
        except BaseException as error:
            stuck = [name for name in reversed(done) if not _put_back(folder / name, before[name])]
            if stuck:
                raise OSError("a write failed and these files could not be put back: " + ", ".join(stuck)) from error
            raise
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)


def write_json(path: str | os.PathLike[str], data: dict[str, Any]) -> None:
    """Write ``data`` with :func:`render_json`, creating the folder if needed, all or nothing."""
    target = Path(path)
    commit_files(target.parent, {target.name: render_json(data)}, last=target.name)


# ---- the manifest -----------------------------------------------------------------------------


def _calendar_date(text: Any) -> bool:
    if not isinstance(text, str) or _ISO_DATE.fullmatch(text) is None:
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _valid_input(record: Any) -> bool:
    return (
        isinstance(record, dict)
        and isinstance(record.get("file"), str)
        and record["file"] != ""
        and isinstance(record.get("sha256"), str)
        and _SHA256.fullmatch(record["sha256"]) is not None
        and _calendar_date(record.get("date"))
    )


def _valid_output(record: Any) -> bool:
    return (
        isinstance(record, dict)
        and isinstance(record.get("file"), str)
        and record["file"] != ""
        and isinstance(record.get("inputs"), list)
        and all(isinstance(name, str) for name in record["inputs"])
        and _calendar_date(record.get("generated"))
    )


class _BadManifest(ValueError):
    """The manifest parses as JSON but is not in the form this tool writes."""


def _by_file(records: Any, valid: Callable[[Any], bool]) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list) or not all(valid(record) for record in records):
        raise _BadManifest("a record is not in the form this tool writes")
    by_file = {record["file"]: record for record in records}
    if len(by_file) != len(records):
        raise _BadManifest("a file is listed twice")
    return by_file


def read_manifest(out_dir: str | os.PathLike[str]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """The records of ``manifest.json`` as ``(inputs, outputs)``, each ``{file name: record}``;
    two empty dicts when there is no manifest yet.

    The manifest is what a later build compares each derived file's recorded hashes against, so one
    that cannot be read or is not in the form this tool writes is an error (:class:`ValueError`) and
    is never overwritten.
    """
    path = Path(out_dir) / MANIFEST_FILE
    if not path.exists():
        return {}, {}
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        return _by_file(current["inputs"], _valid_input), _by_file(current["outputs"], _valid_output)
    except _BadManifest as exc:
        raise ValueError(f"{MANIFEST_FILE} cannot be read, so it was left alone ({exc})") from exc
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{MANIFEST_FILE} cannot be read, so it was left alone ({type(exc).__name__})") from exc


def merge_manifest(
    known: tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]],
    inputs: list[dict[str, str]],
    outputs: list[dict[str, Any]],
    generated: str,
) -> dict[str, Any]:
    """The manifest after adding ``inputs`` and ``outputs`` to what :func:`read_manifest` found.

    ``inputs`` are :func:`input_record` results and ``outputs`` are
    ``{"file", "inputs": [resource names], "generated"}``. Records are matched by ``file``: a new
    record replaces the old one, the others are kept, and both lists are sorted by ``file``.
    """
    known_inputs = {**known[0], **{item["file"]: item for item in inputs}}
    known_outputs = {**known[1], **{item["file"]: item for item in outputs}}
    return {
        "generated": generated,
        "inputs": [known_inputs[name] for name in sorted(known_inputs)],
        "outputs": [known_outputs[name] for name in sorted(known_outputs)],
    }


def update_manifest(
    out_dir: str | os.PathLike[str],
    inputs: list[dict[str, str]],
    outputs: list[dict[str, Any]],
    generated: str,
) -> dict[str, Any]:
    """Merge input and output records into ``manifest.json`` and return the merged manifest.

    A manifest that cannot be read is an error and is left alone (:func:`read_manifest`).
    """
    manifest = merge_manifest(read_manifest(out_dir), inputs, outputs, generated)
    write_json(Path(out_dir) / MANIFEST_FILE, manifest)
    return manifest


# ---- the command line -----------------------------------------------------------------------

_TABLES: tuple[tuple[str, str, Callable[..., dict[str, Any]], str], ...] = (
    ("zones.json", ZONES_FILE, read_zones, "zones"),
    ("basedata.json", BASEDATA_FILE, read_basedata, "basedata"),
    ("acmitigation.json", ACMITIGATION_FILE, read_acmitigation, "acmitigation"),
    ("skillcaps.json", SKILLCAPS_FILE, read_skillcaps, "skillcaps"),
)


def _summary(name: str, table: dict[str, Any]) -> str:
    if name == "zones.json":
        return f"{name}: {len(table['zones'])} zones, {table['flagged_count']} flagged"
    return f"{name}: {len(table['rows'])} rows (levels 1 to {MAX_TABLE_LEVEL})"


def generate(client_dir: str | os.PathLike[str], out_dir: str | os.PathLike[str], generated: str) -> list[str]:
    """Read the four resources, write the four derived files and the manifest; return summary lines.

    The old manifest is read and checked first, then everything is read and checked, and every text is
    made, before the first file is written; the files are then put in place all or nothing, the manifest
    last (:func:`commit_files`). So a missing resource, a malformed table, a table below its row floor,
    a manifest that cannot be read or a resource that changes while it is read leaves the output folder
    as it was.
    """
    root = Path(client_dir)
    missing = [name for name in INPUT_FILES if not (root / name).is_file()]
    if missing:
        raise MissingInput("missing input file: " + ", ".join(missing))
    out = Path(out_dir)
    known = read_manifest(out)
    parsed = []
    for output, resource, reader, floor in _TABLES:
        record, table = read_checked(
            root, resource, lambda path, reader=reader, floor=floor: reader(path, minimum_rows=MINIMUM_ROWS[floor])
        )
        parsed.append((output, record, table))
    texts = {
        output: render_json({"provenance": provenance([record], generated), **table})
        for output, record, table in parsed
    }
    manifest = merge_manifest(
        known,
        [record for _, record, _ in parsed],
        [{"file": output, "inputs": [record["file"]], "generated": generated} for output, record, _ in parsed],
        generated,
    )
    texts[MANIFEST_FILE] = render_json(manifest)
    commit_files(out, texts)
    return [_summary(output, table) for output, _, table in parsed]


def iso_date(text: str) -> str:
    """An ``argparse`` type: a calendar date written YYYY-MM-DD, nothing looser."""
    if not _calendar_date(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not a date written YYYY-MM-DD")
    return text


def one_line(error: BaseException) -> str:
    """The message of an error on one line: runs of white space become one space. An error with no
    message gives the name of its type."""
    return " ".join(str(error).split()) or type(error).__name__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.sources.client_tables",
        description="Write the client's zone, pool, softcap and skill-cap tables as derived JSON.",
    )
    parser.add_argument(
        "--client-dir",
        type=Path,
        help=f"install folder (default: ${ENV_CLIENT_DIR}, else the stock folder under %%PUBLIC%%)",
    )
    parser.add_argument("--out", type=Path, default=Path("derived/client"), help="output folder")
    parser.add_argument("--date", type=iso_date, help="generation date, YYYY-MM-DD (default: today in UTC)")
    args = parser.parse_args(argv)
    client_dir = resolve_client_dir(args.client_dir)
    if client_dir is None:
        print(f"error: no client folder: pass --client-dir or set {ENV_CLIENT_DIR}", file=sys.stderr)
        return 2
    generated = args.date or today_utc()
    try:
        summary = generate(client_dir, args.out, generated)
    except (OSError, ValueError) as exc:
        print(f"error: {one_line(exc)}", file=sys.stderr)
        return 2
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
