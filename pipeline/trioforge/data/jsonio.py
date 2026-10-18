"""Strict JSON in, one record per line out: the two things every derived and rules file needs.

* :func:`load_strict` reads a file the way every other JSON parser would: UTF-8, no byte order mark, no
  duplicate object key (parsers keep only the last, so a duplicate is an edit that silently loses
  data), no ``NaN`` or ``Infinity``. An error names the file and what is wrong, never the content.
* :func:`render` writes a dict as text for a derived file: the keys in the order given, and for the keys
  named in ``per_line`` a list's items (or a dict's entries) one per line, so a git diff shows one
  changed item as one changed line. The output is strict JSON in UTF-8 with ``\\n`` line ends, the same
  bytes for the same data. A lone surrogate, which no UTF-8 file can hold, is refused instead of written.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

__all__ = ["JsonFileError", "MAX_FILE_BYTES", "load_strict", "loads_strict", "render"]

MAX_FILE_BYTES = 256 * 1024 * 1024  # a derived file is a few MB; the limit only stops a runaway file
_SURROGATE = re.compile("[\ud800-\udfff]")


class JsonFileError(ValueError):
    """A JSON file cannot be read as strict JSON. The message names the file and the fault, not the content."""


class _Duplicate(ValueError):
    pass


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _Duplicate("an object repeats a key")
        result[key] = value
    return result


def _no_constants(name: str) -> Any:
    raise _Duplicate(f"{name} is not a JSON number")


def loads_strict(text: str, source: str = "<memory>") -> Any:
    """Parse JSON text strictly (see the module docstring); :class:`JsonFileError` names ``source``."""
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constants)
    except _Duplicate as error:
        raise JsonFileError(f"{source}: {error}") from None
    except json.JSONDecodeError as error:
        raise JsonFileError(f"{source}: not valid JSON (line {error.lineno}, column {error.colno})") from None
    except (RecursionError, ValueError) as error:  # nesting too deep, or a number too long to read
        raise JsonFileError(f"{source}: cannot be read as JSON ({type(error).__name__})") from None


def load_strict(path: str | os.PathLike[str]) -> Any:
    """Read a JSON file strictly. Raises :class:`JsonFileError` for a bad file, ``OSError`` if unreadable."""
    source = Path(path)
    with source.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise JsonFileError(f"{source.name}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MiB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise JsonFileError(f"{source.name}: not valid UTF-8") from None
    return loads_strict(text, source.name)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def render(data: dict[str, Any], *, per_line: Iterable[str] = ()) -> str:
    """Text for a derived JSON file (see the module docstring)."""
    expand = set(per_line)
    lines = ["{"]
    last = len(data) - 1
    for position, (key, value) in enumerate(data.items()):
        if not isinstance(key, str):
            raise TypeError(f"JSON keys must be text, not {key!r}")
        comma = "," if position < last else ""
        if key in expand and isinstance(value, list) and value:
            lines.append(f" {_dump(key)}: [")
            for index, item in enumerate(value):
                lines.append(f"  {_dump(item)}{',' if index < len(value) - 1 else ''}")
            lines.append(f" ]{comma}")
        elif key in expand and isinstance(value, dict) and value:
            lines.append(f" {_dump(key)}: {{")
            entries = list(value.items())
            for index, (name, entry) in enumerate(entries):
                if not isinstance(name, str):
                    raise TypeError(f"JSON keys must be text, not {name!r}")
                lines.append(f"  {_dump(name)}:{_dump(entry)}{',' if index < len(entries) - 1 else ''}")
            lines.append(f" }}{comma}")
        else:
            lines.append(f" {_dump(key)}: {_dump(value)}{comma}")
    lines.append("}")
    text = "\n".join(lines) + "\n"
    if _SURROGATE.search(text):
        raise ValueError("the data holds a lone surrogate character, which no UTF-8 file can hold")
    return text
