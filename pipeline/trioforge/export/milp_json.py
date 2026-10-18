"""Model JSON v1: the MILP of the builder as plain data, and the comparison that holds two builders to each other.

The browser engine builds the same program as :func:`trioforge.solver.model.build_milp` and a parity test compares the two,
so the program has a data form both sides write and read::

    {"version": 1, "sense": "max", "const": c,
     "col_names": [...], "col_lb": [...], "col_ub": [...], "integrality": [...], "c": [...],
     "row_names": [...], "row_lb": [...], "row_ub": [...],
     "A": {"start": [...], "index": [...], "value": [...]},
     "item_cols": [[col, group, key, tier]],
     "buff_cols": [[col, buff_id]],
     "info": {...}}

* The program is ``maximize const + c . x`` (``sense``) over ``row_lb <= A x <= row_ub``, ``col_lb <= x <= col_ub`` with the
  columns of ``integrality`` 1 integer. The columns and rows are in the builder's exact order and every row has a name
  (``Milp.row_names``), so a difference can be named. ``A`` is in compressed row form: row ``r`` is
  ``index[start[r]:start[r + 1]]`` and ``value[...]``, the column indices rising within a row.
* The finite bounds of an integer column are whole numbers: the solver is wrong on a column like ``0.5 <= x <= 2.5``, so a document
  with one is refused (it is never rounded).
* **The two readers agree.** The browser's reader (``static/engine/protocol.js``) takes the documents this module takes and refuses
  the ones it refuses; the files of ``fixtures/milp/`` are judged by both. The names of the columns and rows, the group and key of an
  item column and the keys and texts of ``info`` are labels: any text, of any length, with any character. What the browser cannot take
  is refused here too: a buff id (the one whole number that names something) beyond ±(2**53 - 1), which a double holds exactly; a
  number too big for a double; an ``info`` that is not plain data (a number that is not finite, more than 8 levels or 100,000 values,
  or a key that could poison a lookup there: ``__proto__``, ``constructor``, ``prototype``); and a model of more than 50,000 columns,
  50,000 rows or 1,000,000 entries of the matrix. A number of a float field is read as the double it is, so bounds are compared as
  doubles: two whole numbers beyond 2**53 that differ by one are the same bound. The browser reads a parsed document, not its text, so
  it cannot see a whole number written as ``1.0`` (to a parsed document it is ``1``, and this module refuses it where a flag, an
  index, a tier or an id is meant) or a key written twice in one object (:func:`loads` refuses the text; a parser keeps the last): the
  two places where it takes what this module refuses.
* An infinite bound is ``null``. ``item_cols`` lists the columns that count the copies of an item worn in a group and
  ``buff_cols`` the columns that choose an optional buff, in column order. ``info`` describes the build; it is data for
  the reader and is not compared.
* The text (:func:`to_json`, :func:`dumps`) is canonical: the keys in the order above, no spaces, plain ASCII, numbers as
  Python writes them (the shortest text that reads back to the same double), ``-0.0`` written as ``0.0`` and no ``NaN`` or
  ``Infinity``. A model that holds one is refused. :func:`loads` reads text strictly and :func:`validate` lists the faults
  of a document.

**The parity rules** (:func:`compare`): the column names, their integrality and the row set are identical, in identical
order (a row or a column that the other side lacks is named, and so is a change of order of those they share); coefficients,
bounds, the constant and the objective agree within ``|a - b| <= 1e-12 * max(1, |a|, |b|)``; an infinite bound agrees only
with an infinite one, never with a number. A coefficient that is missing and one that is stored as 0 are the same. The
messages say what ``b`` is, seen from ``a``: *missing* is in ``a`` and not in ``b``, *extra* is in ``b`` and not in ``a``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["KEYS", "LIMIT", "TOLERANCE", "VERSION", "compare", "dumps", "loads", "to_dict", "to_json", "validate"]

VERSION = 1
KEYS = (
    "version", "sense", "const", "col_names", "col_lb", "col_ub", "integrality", "c", "row_names", "row_lb", "row_ub", "A",
    "item_cols", "buff_cols", "info",
)
MATRIX_KEYS = ("start", "index", "value")
SENSES = ("max", "min")
TOLERANCE = 1e-12  # relative, with a floor of 1
LIMIT = 100  # the most differences :func:`compare` lists; the rest are counted
MAX_TIER = 10
#: The limits of what the browser takes (``LIMITS`` in static/engine/protocol.js; the fixtures carry them, so that a test holds the two together).
MAX_COLUMNS = 50_000
MAX_ROWS = 50_000
MAX_NONZEROS = 1_000_000
MAX_INFO_DEPTH = 8  # containers on one path of the info, the info itself the first
MAX_INFO_NODES = 100_000  # values in the info, the info itself and every container included
MAX_SAFE_INTEGER = 2**53 - 1  # the whole numbers a double holds exactly (Number.MAX_SAFE_INTEGER)
POISON_KEYS = ("__proto__", "constructor", "prototype")  # keys the browser refuses in data: they could change what a lookup finds


# ---- writing -------------------------------------------------------------------------------------------------------------


def _finite(value: Any, what: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} is not a finite number: {value!r}")
    return number + 0.0  # -0.0 + 0.0 is 0.0: one text for one number


def _bound(value: Any, what: str, *, lower: bool) -> float | None:
    number = float(value)
    if math.isnan(number):
        raise ValueError(f"{what} is not a number")
    if math.isinf(number):
        if (number > 0) == lower:  # a lower bound of +inf or an upper bound of -inf: no value is allowed
            raise ValueError(f"{what} is {number}: no value satisfies it")
        return None
    return number + 0.0


def _plain(value: Any) -> Any:
    """JSON data from the builder's ``info`` (tuples as lists, keys in order)."""
    if isinstance(value, Mapping):
        return {str(key): _plain(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int, float)):
        return value
    if hasattr(value, "item"):  # a numpy scalar
        return _plain(value.item())
    raise ValueError(f"info holds {value!r}, which is not JSON data")


def to_dict(milp: Any) -> dict[str, Any]:
    """The model JSON v1 document of a :class:`~trioforge.solver.model.Milp` (see the module docstring).

    Raises ``ValueError`` for a model that cannot be written: a number that is not finite (apart from an infinite bound),
    a bound that no value satisfies, or rows without names (a model not made by the builder)."""
    rows = int(milp.row_lb.shape[0])
    if len(milp.row_names) != rows:
        raise ValueError(f"the model has {rows} rows and {len(milp.row_names)} row names")
    document = {
        "version": VERSION,
        "sense": milp.sense,
        "const": _finite(milp.const, "the constant"),
        "col_names": list(milp.names),
        "col_lb": [_bound(v, "a column lower bound", lower=True) for v in milp.col_lb.tolist()],
        "col_ub": [_bound(v, "a column upper bound", lower=False) for v in milp.col_ub.tolist()],
        "integrality": [int(v) for v in milp.integrality.tolist()],
        "c": [_finite(v, "an objective coefficient") for v in milp.c.tolist()],
        "row_names": list(milp.row_names),
        "row_lb": [_bound(v, "a row lower bound", lower=True) for v in milp.row_lb.tolist()],
        "row_ub": [_bound(v, "a row upper bound", lower=False) for v in milp.row_ub.tolist()],
        "A": {
            "start": [int(v) for v in milp.A.start.tolist()],
            "index": [int(v) for v in milp.A.index.tolist()],
            "value": [_finite(v, "a matrix coefficient") for v in milp.A.value.tolist()],
        },
        "item_cols": [[int(col), group, item.key, int(item.tier)] for col, group, item in milp.item_cols],
        "buff_cols": [[int(col), int(bid)] for col, bid in sorted(milp.buff_cols.items())],
        "info": _plain(milp.info),
    }
    problems = validate(document)
    if problems:
        raise ValueError("the model cannot be written as model JSON v1: " + "; ".join(problems[:5]))
    return document


def _ordered(document: Mapping[str, Any]) -> dict[str, Any]:
    """The document with its keys in the canonical order."""
    ordered = {key: document[key] for key in KEYS}
    ordered["A"] = {key: document["A"][key] for key in MATRIX_KEYS}
    ordered["info"] = _plain(document["info"])
    return ordered


def dumps(document: Mapping[str, Any]) -> str:
    """The canonical text of a document (see the module docstring); the document must be valid."""
    problems = validate(document)
    if problems:
        raise ValueError("not a model JSON v1 document: " + "; ".join(problems[:5]))
    return json.dumps(_ordered(document), separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def to_json(milp: Any) -> str:
    """The canonical text of a model: ``dumps(to_dict(milp))``."""
    return dumps(to_dict(milp))


# ---- reading -------------------------------------------------------------------------------------------------------------


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r} in one object (parsers keep only the last)")
        result[key] = value
    return result


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON number (a model has finite numbers and null)")


def _parse(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except RecursionError as error:  # a document nested deeper than the parser reads: not a model, and not a crash
        raise ValueError("the text is nested too deeply to be read") from error


def loads(text: str) -> dict[str, Any]:
    """The document of canonical (or any key order) model JSON text. Strict: refuses duplicate keys, ``NaN``, ``Infinity``,
    a missing or unknown field and any fault :func:`validate` finds. Raises ``ValueError``."""
    document = _parse(text)
    problems = validate(document)
    if problems:
        raise ValueError("not a model JSON v1 document: " + "; ".join(problems[:5]))
    return document


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(value)
    except OverflowError:  # a whole number too big for a double (the browser reads it as Infinity)
        return False


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and _is_finite(value)


def _info_faults(info: Any) -> list[str]:
    """The faults of an ``info``: an object of plain JSON data (null, booleans, finite numbers, text, lists and objects with text for keys), of at most
    ``MAX_INFO_DEPTH`` levels and ``MAX_INFO_NODES`` values, without the keys that could poison a lookup in the browser. The walk keeps its own stack,
    so that no document can exhaust the call stack; it stops at the first fault."""
    if not isinstance(info, Mapping):
        return ["info is an object"]
    stack: list[tuple[Any, int]] = [(info, 0)]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_INFO_NODES:
            return [f"info has more than {MAX_INFO_NODES} values"]
        if value is None or isinstance(value, (bool, str)):
            continue
        if isinstance(value, (int, float)):
            if not _is_finite(value):
                return ["info holds a number that is not finite"]
            continue
        if not isinstance(value, (Mapping, list, tuple)):
            return ["info holds something that is not JSON data"]
        if depth >= MAX_INFO_DEPTH:
            return [f"info is nested more than {MAX_INFO_DEPTH} levels deep"]
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    return ["info has a key that is not text"]
                if key in POISON_KEYS:
                    return [f"info has the key {key}, which could poison a lookup in the browser"]
                stack.append((item, depth + 1))
        else:
            stack.extend((item, depth + 1) for item in value)
    return []


def _names(document: Mapping[str, Any], key: str, what: str, out: list[str]) -> int | None:
    names = document[key]
    if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
        out.append(f"{key} is not a list of names")
        return None
    if len(set(names)) != len(names):
        out.append(f"a {what} name is used twice")
    return len(names)


def _bounds(document: Mapping[str, Any], low: str, high: str, count: int | None, what: str, out: list[str]) -> None:
    lows, highs = document[low], document[high]
    for key, values in ((low, lows), (high, highs)):
        if not isinstance(values, list) or (count is not None and len(values) != count):
            out.append(f"{key} is not a list of {count} bounds")
            return
        if not all(v is None or _is_number(v) for v in values):
            out.append(f"{key} holds something that is neither a finite number nor null")
            return
    for at, (a, b) in enumerate(zip(lows, highs)):
        # (compared as the doubles they are read as: two whole numbers beyond 2**53 that differ by one are the same double, to the browser and to the solver)
        if a is not None and b is not None and float(a) > float(b):
            out.append(f"{what} {at} has a lower bound above its upper bound")
            return


def _is_whole(value: Any) -> bool:
    return isinstance(value, int) or float(value).is_integer()


def _integer_bounds(document: Mapping[str, Any], cols: int, out: list[str]) -> None:
    """An integer column's finite bounds are whole numbers. HiGHS with the presolve off, as the solver runs, gives a wrong answer
    that it calls optimal for a column like ``0.5 <= x <= 2.5`` (and sometimes aborts), so a document with one is refused, and it
    is not rounded: rounding would only move the error to the one who rounds. The faults that make this check meaningless (lists of
    other lengths, bounds that are not numbers) are reported by the checks of those fields."""
    flags, lows, highs, names = document["integrality"], document["col_lb"], document["col_ub"], document["col_names"]
    if not all(isinstance(v, list) and len(v) == cols for v in (flags, lows, highs, names)):
        return
    for at in range(cols):
        if not _is_int(flags[at]) or flags[at] != 1:
            continue
        for value, label in ((lows[at], "a lower"), (highs[at], "an upper")):
            if value is not None and _is_number(value) and not _is_whole(value):
                out.append(f"integer column {names[at]!s} has {label} bound that is not a whole number")


def validate(document: Any) -> list[str]:
    """The faults of a model JSON v1 document as texts (an empty list: it is one): the fields, the lengths, the names, the
    bounds (and that an integer column's are whole numbers), the matrix in compressed row form and the item and buff columns."""
    if not isinstance(document, Mapping):
        return ["the document is not an object"]
    missing, unknown = [k for k in KEYS if k not in document], [k for k in document if k not in KEYS]
    if missing or unknown:
        return [f"the fields are {', '.join(KEYS)} (missing {missing}, unexpected {unknown})"]
    out: list[str] = []
    if document["version"] != VERSION or not _is_int(document["version"]):
        out.append(f"version is {VERSION}, not {document['version']!r}")
    if document["sense"] not in SENSES:
        out.append(f"sense is one of {', '.join(SENSES)}, not {document['sense']!r}")
    if not _is_number(document["const"]):
        out.append("const is not a finite number")
    cols = _names(document, "col_names", "column", out)
    rows = _names(document, "row_names", "row", out)
    if cols is not None and cols > MAX_COLUMNS:
        out.append(f"a model has at most {MAX_COLUMNS} columns")
    if rows is not None and rows > MAX_ROWS:
        out.append(f"a model has at most {MAX_ROWS} rows")
    _bounds(document, "col_lb", "col_ub", cols, "column", out)
    _bounds(document, "row_lb", "row_ub", rows, "row", out)
    for key in ("integrality", "c"):
        values = document[key]
        if not isinstance(values, list) or (cols is not None and len(values) != cols):
            out.append(f"{key} is not a list of {cols} values")
        elif key == "integrality" and not all(_is_int(v) and v in (0, 1) for v in values):
            out.append("integrality holds something other than 0 and 1")
        elif key == "c" and not all(_is_number(v) for v in values):
            out.append("c holds something that is not a finite number")
    if cols is not None:
        _integer_bounds(document, cols, out)
    matrix = document["A"]
    if not isinstance(matrix, Mapping) or set(matrix) != set(MATRIX_KEYS):
        out.append("A has start, index and value")
    else:
        start, index, value = matrix["start"], matrix["index"], matrix["value"]
        if not all(isinstance(v, list) for v in (start, index, value)):
            out.append("A.start, A.index and A.value are lists")
        elif rows is not None and cols is not None:
            if len(start) != rows + 1 or not all(_is_int(v) for v in start) or start[0] != 0:
                out.append(f"A.start has {rows + 1} whole numbers from 0")
            elif any(a > b for a, b in zip(start, start[1:])) or start[-1] != len(index) or len(index) != len(value):
                out.append("A.start rises to the number of entries of A.index and A.value, which are as long as each other")
            elif start[-1] > MAX_NONZEROS:
                out.append(f"A has at most {MAX_NONZEROS} entries")
            elif not all(_is_int(v) and 0 <= v < cols for v in index):
                out.append("A.index names a column that does not exist")
            elif not all(_is_number(v) for v in value):
                out.append("A.value holds something that is not a finite number")
            elif any(a >= b for r in range(rows) for a, b in zip(index[start[r]:start[r + 1]], index[start[r] + 1:start[r + 1]])):
                out.append("the column indices of a row of A rise strictly")
    if cols is not None:
        items, buffs = document["item_cols"], document["buff_cols"]
        if not isinstance(items, list) or not all(
            isinstance(e, list) and len(e) == 4 and _is_int(e[0]) and 0 <= e[0] < cols and isinstance(e[1], str)
            and isinstance(e[2], str) and _is_int(e[3]) and 0 <= e[3] <= MAX_TIER for e in items
        ):
            out.append("item_cols is a list of [column, group, key, tier]")
        elif len({e[0] for e in items}) != len(items):
            out.append("item_cols names a column twice")
        if not isinstance(buffs, list) or not all(
            isinstance(e, list) and len(e) == 2 and _is_int(e[0]) and 0 <= e[0] < cols and _is_int(e[1]) and abs(e[1]) <= MAX_SAFE_INTEGER
            for e in buffs
        ):
            out.append("buff_cols is a list of [column, buff id], the id a whole number of at most 2**53 - 1 in size")
        elif len({e[0] for e in buffs}) != len(buffs):
            out.append("buff_cols names a column twice")
    out.extend(_info_faults(document["info"]))
    return out


# ---- compare -------------------------------------------------------------------------------------------------------------


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE * max(1.0, abs(a), abs(b))


def _same_bound(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return _close(a, b)


def _show(bound: float | None) -> str:
    return "unbounded" if bound is None else repr(bound)


def _order(names_a: Sequence[str], names_b: Sequence[str], what: str, out: list[str]) -> set[str]:
    """Name what one side lacks and the change of order of the names both have; the names both have."""
    in_a, in_b = set(names_a), set(names_b)
    out += [f"missing {what}: {name}" for name in names_a if name not in in_b]
    out += [f"extra {what}: {name}" for name in names_b if name not in in_a]
    common_a = [name for name in names_a if name in in_b]
    common_b = [name for name in names_b if name in in_a]
    if common_a != common_b:
        at = next(i for i, (x, y) in enumerate(zip(common_a, common_b)) if x != y)
        out.append(f"{what} order changed: first difference at position {at} ({common_a[at]} vs {common_b[at]})")
    return in_a & in_b


def _row_entries(document: Mapping[str, Any], r: int) -> dict[str, float]:
    matrix, names = document["A"], document["col_names"]
    return {names[matrix["index"][k]]: matrix["value"][k] for k in range(matrix["start"][r], matrix["start"][r + 1])}


def _tagged(document: Mapping[str, Any], key: str) -> list[tuple[Any, ...]]:
    names = document["col_names"]
    return [(names[col], *rest) for col, *rest in document[key]]


def _cut(lines: list[str], limit: int) -> list[str]:
    return lines if len(lines) <= limit else [*lines[:limit], f"... and {len(lines) - limit} more"]


def compare(a: Mapping[str, Any] | str, b: Mapping[str, Any] | str, *, limit: int = LIMIT) -> list[str]:
    """What differs between two model JSON documents (or their text) under the parity rules of the module docstring; an empty
    list means they agree. The messages are ordered: header, columns (their names and order, then each by name), rows (the
    same, with the first differing row first), then the item and buff columns. ``limit`` cuts a long list.

    A document of another version is reported alone; an invalid document is reported by its faults, not compared."""
    doc_a = _parse(a) if isinstance(a, str) else a
    doc_b = _parse(b) if isinstance(b, str) else b
    version_a = doc_a.get("version") if isinstance(doc_a, Mapping) else None
    version_b = doc_b.get("version") if isinstance(doc_b, Mapping) else None
    if version_a != version_b:
        return [f"version differs: {version_a} vs {version_b}"]
    invalid = [f"invalid model a: {p}" for p in validate(doc_a)] + [f"invalid model b: {p}" for p in validate(doc_b)]
    if invalid:
        return _cut(invalid, limit)
    out: list[str] = []
    if doc_a["sense"] != doc_b["sense"]:
        out.append(f"sense differs: {doc_a['sense']!r} vs {doc_b['sense']!r}")
    if not _close(doc_a["const"], doc_b["const"]):
        out.append(f"constant differs: {doc_a['const']!r} vs {doc_b['const']!r}")

    at_a = {name: i for i, name in enumerate(doc_a["col_names"])}
    at_b = {name: i for i, name in enumerate(doc_b["col_names"])}
    columns = _order(doc_a["col_names"], doc_b["col_names"], "column", out)
    for name in doc_a["col_names"]:
        if name not in columns:
            continue
        i, j = at_a[name], at_b[name]
        if doc_a["integrality"][i] != doc_b["integrality"][j]:
            out.append(f"integrality differs: {name}")
        for key, label in (("col_lb", "lower"), ("col_ub", "upper")):
            x, y = doc_a[key][i], doc_b[key][j]
            if not _same_bound(x, y):
                out.append(f"column {label} bound differs: {name} ({_show(x)} vs {_show(y)})")
        if not _close(doc_a["c"][i], doc_b["c"][j]):
            out.append(f"objective coefficient differs: {name} ({doc_a['c'][i]!r} vs {doc_b['c'][j]!r})")

    row_at_a = {name: i for i, name in enumerate(doc_a["row_names"])}
    row_at_b = {name: i for i, name in enumerate(doc_b["row_names"])}
    both = _order(doc_a["row_names"], doc_b["row_names"], "row", out)
    for name in doc_a["row_names"]:
        if name not in both:
            continue
        r, s = row_at_a[name], row_at_b[name]
        for key, label in (("row_lb", "lower"), ("row_ub", "upper")):
            x, y = doc_a[key][r], doc_b[key][s]
            if not _same_bound(x, y):
                out.append(f"row {label} bound differs: {name} ({_show(x)} vs {_show(y)})")
        entries_a, entries_b = _row_entries(doc_a, r), _row_entries(doc_b, s)
        for column in [*entries_a, *(c for c in entries_b if c not in entries_a)]:
            x, y = entries_a.get(column, 0.0), entries_b.get(column, 0.0)
            if not _close(x, y):
                out.append(f"coefficient differs: row {name}, column {column} ({x!r} vs {y!r})")

    for key, label in (("item_cols", "item columns"), ("buff_cols", "buff columns")):
        tagged_a, tagged_b = _tagged(doc_a, key), _tagged(doc_b, key)
        if tagged_a != tagged_b:
            at = next((i for i, (x, y) in enumerate(zip(tagged_a, tagged_b)) if x != y), min(len(tagged_a), len(tagged_b)))
            left = tagged_a[at] if at < len(tagged_a) else "none"
            right = tagged_b[at] if at < len(tagged_b) else "none"
            out.append(f"{label} differ: first difference at position {at} ({left} vs {right})")
    return _cut(out, limit)
