"""The versioned rules file: every model constant, with a seal, a source and a date.

``rules/rules.json`` holds one entry per rule. Read it with :func:`load`::

    rules = load()
    rules.get("level.current")        # the value at the default level, 50
    rules.get("mana.base_l50", 55)    # the 'levels' override for level 55, else the value
    rules.seal("mana.base_l50")       # 'client'
    rules.sources("mana.base_l50")    # [{'kind': 'client-file', 'ref': 'Resources/basedata.txt'}]

Refusing a file that drifts is the point of this module. A rule without a seal,
source or date, an unknown seal, a duplicate id, an open rule without its in-game
test id, a null value on a settled rule or an impossible date all raise
:class:`RulesError`, which lists every problem found, not just the first.

A rule's ``source`` is a list of ``{"kind", "ref"}`` objects, and the file is public:
a source is a URL, a shipped client text file, a public statement, or the fixed label
for the maintainer's own observations (which never carry a count, value or date), and
no ref may cite a client binary. The schema enforces those forms. The loader adds one
relation between fields: a rule with a ``private-*`` source, its own or an
alternative's, has notes without a single digit.

The shape rules live in ``rules/rules.schema.json`` (JSON Schema 2020-12). This
module adds what a schema cannot say:

* unique ids, and calendar dates (the 'date' format is checked);
* strict JSON: no duplicate keys, no NaN or Infinity, no number that overflows to
  infinity (``1e999``), no integer of more than 15 digits (other JSON readers, such as
  the browser's, round those), only string keys, and no nesting deep enough to raise
  ``RecursionError``. :func:`load` checks while it parses; ``Rules(data)`` checks the data
  itself, so a dict built in memory gets the same checks as a file;
* the shape of a curve: an object with both ``breaks`` and ``slopes``, wherever it sits in
  a value, has one more slope than breaks, strictly increasing breaks and finite slopes;
* the notes rule above.

It also keeps superseded rules out of :meth:`Rules.get`, :meth:`Rules.seal` and
:meth:`Rules.sources`.

The package is run straight from the repository (``PYTHONPATH=pipeline``), so the
schema and the default rules file are found relative to this file.
"""

import copy
import functools
import json
import math
import operator
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

__all__ = ["DEFAULT_LEVEL", "RULES_PATH", "SCHEMA_PATH", "Rules", "RulesError", "load"]

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = REPO_ROOT / "rules" / "rules.json"
SCHEMA_PATH = REPO_ROOT / "rules" / "rules.schema.json"

DEFAULT_LEVEL = 50

# An integer of up to 15 digits is exact as an IEEE double, the only number a browser's
# JSON.parse has; a longer one would be rounded there and read differently.
MAX_INTEGER_DIGITS = 15
_INTEGER_LIMIT = 10**MAX_INTEGER_DIGITS


class RulesError(ValueError):
    """The rules file is invalid. ``problems`` lists every defect found."""

    def __init__(self, problems: list[str], source: str = "<memory>") -> None:
        self.problems = list(problems)
        self.source = source
        count = len(self.problems)
        head = f"invalid rules file {source}: {count} problem{'s' if count != 1 else ''}"
        super().__init__("\n".join([head, *(f"  - {problem}" for problem in self.problems)]))


class Rules:
    """A validated rules file.

    ``Rules(data)`` validates an in-memory file (the shape of ``rules.json``) and
    raises :class:`RulesError` if it is invalid; :func:`load` reads one from disk. A dict
    gets the checks a file gets, the strict-JSON ones included, as far as they can apply to
    a dict (it cannot hold a duplicate key).
    """

    def __init__(self, data: Any, *, source: str = "<memory>") -> None:
        try:
            problems = _problems(data)
            if not problems:
                data = copy.deepcopy(data)  # later changes to the caller's dict must not leak in
        except RecursionError as exc:  # nested too deeply for the checks and the copy, or looping
            raise RulesError([_TOO_DEEP_TO_CHECK], source) from exc
        if problems:
            raise RulesError(problems, source)
        self.version: str = data["version"]
        self._by_id: dict[str, dict[str, Any]] = {rule["id"]: rule for rule in data["rules"]}

    def __repr__(self) -> str:
        return f"Rules(version={self.version!r}, rules={len(self._by_id)})"

    def get(self, id: str, level: int = DEFAULT_LEVEL) -> Any:
        """Return the rule's value at ``level``.

        ``levels[str(level)]`` if the rule has an override for that level, else
        ``value``. The result is a copy, so callers may change it freely. Raises
        ``KeyError`` for an unknown or superseded id, ``TypeError`` if ``level`` is
        not an integer (a float would silently miss every override, and a bool would
        pick the level-1 override: ``True`` is the integer 1) and ``ValueError`` if it
        is negative.
        """
        key = _level_key(level)
        rule = self._active(id)
        levels = rule.get("levels")
        value = levels[key] if levels is not None and key in levels else rule["value"]
        return copy.deepcopy(value)

    def seal(self, id: str) -> str:
        """Return the rule's confidence seal. Raises ``KeyError`` like :meth:`get`."""
        return self._active(id)["seal"]

    def sources(self, id: str) -> list[dict[str, str]]:
        """Return the rule's sources: a list of ``{"kind", "ref"}`` objects, in file order.

        The result is a copy, so callers may change it freely. Raises ``KeyError`` like
        :meth:`get`.
        """
        return copy.deepcopy(self._active(id)["source"])

    def alternatives(self, id: str) -> list[dict[str, Any]]:
        """Return the rule's alternative readings: a list of ``{"value", "seal", "source"}`` objects, in file order.

        An open rule can list the other values it might take (``mana.wis_bands`` lists the measured WIS band); the
        robustness runs try each. The result is a copy, so callers may change it freely, and it is empty for a rule
        with no alternatives. Raises ``KeyError`` like :meth:`get`.
        """
        return copy.deepcopy(self._active(id).get("alternatives", []))

    def settled_by(self, id: str) -> str | None:
        """Return the id of the in-game test that settles an open rule (``"B4"``), or ``None`` for a rule that has no
        test. Raises ``KeyError`` like :meth:`get`."""
        return self._active(id).get("test")

    def _active(self, id: str) -> dict[str, Any]:
        rule = self._by_id.get(id)
        if rule is None:
            raise KeyError(f"unknown rule id {id!r}")
        if rule["status"] == "superseded":
            raise KeyError(f"rule {id!r} is superseded")
        return rule


def _level_key(level: int) -> str:
    """The text that ``levels`` is keyed by; ``TypeError`` for a non-integer, ``ValueError`` below zero."""
    if isinstance(level, bool):
        raise TypeError(f"level must be an integer, not the bool {level!r} (True is the integer 1)")
    number = int(operator.index(level))  # TypeError for a float, a str, None, ...
    if number < 0:
        raise ValueError("level must not be negative")
    return str(number)


def load(path: str | os.PathLike[str] | None = None) -> Rules:
    """Read and validate a rules file; ``None`` means the repository's ``rules/rules.json``.

    Raises :class:`RulesError` if the file is not valid UTF-8 / strict JSON or does
    not pass validation, and ``FileNotFoundError`` if it does not exist.
    """
    source = RULES_PATH if path is None else Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RulesError([f"not valid UTF-8: {exc}"], str(source)) from exc
    try:
        data = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_float=_parse_float,
            parse_int=_parse_int,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise RulesError([f"not valid JSON: {exc}"], str(source)) from exc
    except _StrictJsonError as exc:
        raise RulesError([str(exc)], str(source)) from exc
    except RecursionError as exc:  # json.loads gives up on a few thousand brackets
        raise RulesError([_TOO_DEEP_TO_READ], str(source)) from exc
    except ValueError as exc:  # whatever else the reader refuses; a RulesError is never raised in here
        raise RulesError([f"cannot be read as JSON: {exc}"], str(source)) from exc
    return Rules(data, source=str(source))


# ---- strict JSON ---------------------------------------------------------------------


class _StrictJsonError(ValueError):
    """JSON that parses, but that other parsers would read differently."""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # json.loads keeps the last of two equal keys without a word; in a hand-edited rules
    # file that is a silently lost seal or value.
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError(f"duplicate key {key!r} in one object (parsers keep only the last)")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    # Python reads NaN and Infinity; JSON.parse in the browser rejects them.
    raise _StrictJsonError(f"{name} is not a JSON number (use a finite number)")


def _shorten(text: str, limit: int = 24) -> str:
    """A number's text for a message; the literal may be thousands of characters long."""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _parse_float(text: str) -> float:
    # float("1e999") is inf, not an error, so the overflow has to be looked for. JSON.parse in
    # the browser also reads it as Infinity, and JSON.stringify then writes null in its place.
    number = float(text)
    if not math.isfinite(number):
        raise _StrictJsonError(f"{_shorten(text)} is not a finite number (it is too large for a double)")
    return number


def _parse_int(text: str) -> int:
    # Judged on the text, before int() sees it: Python refuses to convert thousands of digits.
    if len(text.lstrip("-")) > MAX_INTEGER_DIGITS:
        raise _StrictJsonError(
            f"the integer {_shorten(text)} has more than {MAX_INTEGER_DIGITS} digits "
            "(other JSON readers would round it)"
        )
    return int(text)


_TOO_DEEP_TO_READ = "nested too deeply to read (a rules file is a shallow object)"
_TOO_DEEP_TO_CHECK = "nested too deeply to check (a rules file is a shallow object), or it contains itself"


# ---- validation ----------------------------------------------------------------------


@functools.cache
def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _problems(data: Any) -> list[str]:
    """Every defect of ``data``, phrased for a human; an empty list means valid.

    Raises ``RecursionError`` for data nested (or looping) past the interpreter's limit;
    :class:`Rules` turns that into a :class:`RulesError`.
    """
    problems = _schema_problems(data)
    problems.extend(_duplicate_ids(data))
    problems.extend(_private_notes_problems(data))
    problems.extend(_strict_problems(data))
    problems.extend(_curve_problems(data))
    # A malformed date breaks both the 'pattern' and the 'format' keyword of the schema.
    return list(dict.fromkeys(problems))


def _schema_problems(data: Any) -> list[str]:
    problems = []
    try:
        for error in _validator().iter_errors(data):
            problems.append(f"{_label(data, error.absolute_path)}: {_describe(error)}")
    except ValueError as exc:
        # jsonschema quotes the offending value in its message, and Python will not print an
        # integer of thousands of digits. The strict check says where that integer is.
        problems.append(f"the schema check stopped early, as a value could not be quoted: {exc}")
    return problems


def _duplicate_ids(data: Any) -> list[str]:
    # JSON Schema's uniqueItems compares whole objects, not one field of them.
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        return []
    first_seen: dict[str, int] = {}
    problems = []
    for index, rule in enumerate(rules):
        rule_id = rule.get("id") if isinstance(rule, dict) else None
        if not isinstance(rule_id, str):
            continue
        if rule_id in first_seen:
            problems.append(
                f"rules[{index}] {rule_id!r}: duplicate rule id (first used at rules[{first_seen[rule_id]}])"
            )
        else:
            first_seen[rule_id] = index
    return problems


PRIVATE_KIND_PREFIX = "private-"


def _private_notes_problems(data: Any) -> list[str]:
    """A rule that rests on a private observation must not give numbers in its notes.

    The sources hide the maintainer's counts, values and dates behind one fixed label, but
    ``notes`` is free text, so it gets a plain rule: no digit at all. ``str.isnumeric`` is
    used rather than ``[0-9]`` so that full-width, Arabic-Indic, superscript and Roman digits
    do not slip through. A private source counts whether it is the rule's own or an
    alternative's. Malformed shapes are skipped here; the schema reports them.
    """
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        return []
    problems = []
    for index, rule in enumerate(rules):
        notes = rule.get("notes") if isinstance(rule, dict) else None
        if not isinstance(notes, str) or not any(character.isnumeric() for character in notes):
            continue
        kinds = sorted(_private_kinds(rule))
        if kinds:
            where = _label(data, ["rules", index, "notes"])
            problems.append(
                f"{where}: notes contain a digit, but the rule rests on a private observation "
                f"({', '.join(kinds)}); counts, values and dates must stay out of the public file"
            )
    return problems


def _private_kinds(rule: dict[str, Any]) -> set[str]:
    """The ``private-*`` source kinds of a rule, its own and its alternatives'."""
    source_lists = [rule.get("source")]
    alternatives = rule.get("alternatives")
    if isinstance(alternatives, list):
        source_lists.extend(item.get("source") for item in alternatives if isinstance(item, dict))
    return {
        entry["kind"]
        for sources in source_lists
        if isinstance(sources, list)
        for entry in sources
        if isinstance(entry, dict)
        and isinstance(entry.get("kind"), str)
        and entry["kind"].startswith(PRIVATE_KIND_PREFIX)
    }


def _strict_problems(data: Any) -> list[str]:
    """What a JSON file could not hold, or that other JSON readers would read differently.

    :func:`load` refuses these while it parses; a ``Rules`` built from a Python dict never
    went through the parser, so this walk makes the same checks on the data itself: a float
    that is not finite, an integer of more than 15 digits, and an object key that is not a
    string (the key pattern of ``levels`` only judges strings, and ``get`` looks a level up
    by its text). The walk recurses on purpose: data nested or looping past the interpreter's
    limit raises ``RecursionError``, which :class:`Rules` turns into a :class:`RulesError`.
    """
    problems: list[str] = []
    _check_strict(data, (), data, problems)
    return problems


def _check_strict(node: Any, path: tuple[Any, ...], root: Any, problems: list[str]) -> None:
    if isinstance(node, float):
        if not math.isfinite(node):
            problems.append(
                f"{_label(root, path)}: {node!r} is not a finite number (JSON has no NaN or Infinity)"
            )
    elif isinstance(node, int):  # a bool is an int too, and never too long
        if abs(node) >= _INTEGER_LIMIT:
            problems.append(
                f"{_label(root, path)}: an integer of more than {MAX_INTEGER_DIGITS} digits "
                "(other JSON readers would round it)"
            )
    elif isinstance(node, dict):
        for key, child in node.items():
            if not isinstance(key, str):
                problems.append(
                    f"{_label(root, path)}: the object key {key!r} is not a string (JSON keys always are)"
                )
            _check_strict(child, (*path, key), root, problems)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _check_strict(child, (*path, index), root, problems)


def _curve_problems(data: Any) -> list[str]:
    """Check every curve in the places where a rule holds a value.

    A curve is any object with both ``breaks`` and ``slopes``, however deep inside the
    rule's ``value``, a ``levels`` value or an alternative's ``value``. Malformed shapes
    are skipped here; the schema reports them.
    """
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        return []
    problems: list[str] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        here = ("rules", index)
        _check_curves(rule.get("value"), (*here, "value"), data, problems)
        levels = rule.get("levels")
        if isinstance(levels, dict):
            for level, level_value in levels.items():
                _check_curves(level_value, (*here, "levels", level), data, problems)
        alternatives = rule.get("alternatives")
        if isinstance(alternatives, list):
            for number, alternative in enumerate(alternatives):
                if isinstance(alternative, dict):
                    where = (*here, "alternatives", number, "value")
                    _check_curves(alternative.get("value"), where, data, problems)
    return problems


def _check_curves(node: Any, path: tuple[Any, ...], root: Any, problems: list[str]) -> None:
    if isinstance(node, dict):
        if "breaks" in node and "slopes" in node:
            problems.extend(_curve_defects(node, path, root))
        for key, child in node.items():
            _check_curves(child, (*path, key), root, problems)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _check_curves(child, (*path, index), root, problems)


def _curve_defects(curve: dict[str, Any], path: tuple[Any, ...], root: Any) -> list[str]:
    """What is wrong with one curve: lists of numbers, one more slope than breaks, breaks that rise.

    A slope that is not finite is reported by the strict check, once, wherever it sits; it is
    not repeated here, and breaks that are not finite are not compared, since that proves nothing.
    """
    breaks, slopes = curve["breaks"], curve["slopes"]
    defects = []
    for name, items in (("breaks", breaks), ("slopes", slopes)):
        if not isinstance(items, list):
            defects.append(f"{_label(root, (*path, name))}: must be a list of numbers")
            continue
        for index, item in enumerate(items):
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                where = _label(root, (*path, name, index))
                defects.append(f"{where}: must be a number, not {type(item).__name__}")
    if defects:
        return defects
    if len(slopes) != len(breaks) + 1:
        defects.append(
            f"{_label(root, path)}: a curve needs one more slope than breaks "
            f"(found {_count(len(breaks), 'break')} and {_count(len(slopes), 'slope')})"
        )
    if all(not isinstance(item, float) or math.isfinite(item) for item in breaks):
        for index in range(len(breaks) - 1):
            if not breaks[index] < breaks[index + 1]:
                defects.append(
                    f"{_label(root, (*path, 'breaks'))}: must be strictly increasing "
                    f"(breaks[{index + 1}] does not exceed breaks[{index}])"
                )
                break
    return defects


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def _label(data: Any, path: Any) -> str:
    """Name a position in the file, such as ``rules[3] 'x.y' alternatives[0].seal``."""
    parts = list(path)
    head = ""
    if len(parts) >= 2 and parts[0] == "rules" and isinstance(parts[1], int):
        head = f"rules[{parts[1]}]"
        rule = data["rules"][parts[1]]
        rule_id = rule.get("id") if isinstance(rule, dict) else None
        if isinstance(rule_id, str):
            head += f" {rule_id!r}"
        parts = parts[2:]
    return " ".join(piece for piece in (head, _render_path(parts)) if piece) or "file"


def _render_path(parts: list[Any]) -> str:
    text = ""
    for part in parts:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else str(part)
    return text


def _describe(error: ValidationError) -> str:
    """Phrase one schema error; jsonschema's own wording is kept where it is already clear."""
    path = list(error.absolute_path)
    field = path[-1] if path else None
    parent = path[-2] if len(path) >= 2 else None
    if error.validator == "required":
        missing = [name for name in error.validator_value if name not in error.instance]
        text = "missing required field " + ", ".join(repr(name) for name in missing)
        if "test" in missing:
            text += " (an open rule must name the in-game test that will settle it, e.g. 'B4')"
        return text
    if error.validator == "type" and error.instance is None and (field == "value" or parent == "levels"):
        return "null is not allowed here: only an open rule may have a null value"
    if error.validator == "pattern" and field == "levels":
        # A bad key: the path is the 'levels' object, and the instance is the key itself.
        return (
            f"{error.instance!r} is not a level "
            "(use a whole number from 1 to 99 without a leading zero, such as '55')"
        )
    if error.validator in ("pattern", "format") and field in ("date", "version"):
        return f"{error.instance!r} is not a valid date (use YYYY-MM-DD)"
    if error.validator == "pattern" and field == "id":
        return f"{error.instance!r} is not a valid id (lowercase words joined by dots, as in 'mana.base_l50')"
    if error.validator == "pattern" and field == "test":
        return f"{error.instance!r} is not an in-game test id (a B and one or two digits, such as 'B4')"
    if error.validator == "pattern" and isinstance(error.instance, str) and not error.instance.strip():
        return "must not be blank"
    if field == "ref":
        # jsonschema's own wording for these three would print a long regex or a bare
        # "was expected"; the position in the label already says which ref is meant.
        if error.validator == "not":
            return (
                "must not cite a client binary, an address in one or a disassembly "
                "(no 'eqgame', '.exe', 'RVA', 'offset' or '0x')"
            )
        if error.validator == "pattern":
            return "is not an https:// address (a host, then an optional path; no spaces, user name or port)"
        if error.validator == "const":
            return f"a private source must use exactly {error.validator_value!r}, never a count, value or date"
    return error.message
