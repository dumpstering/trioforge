"""Cross-check of the catalog against EQL Tools' gear data.

EQL Tools (https://eqltools.com) publishes a gear JSON compiled from eqlwiki and declared CC BY-SA 4.0 (its
code is not licensed and is never used here). It is a second reading of the same wiki pages, so where it and
the catalog differ, one of the two parsers read a page differently or one of them skipped the page: this report
finds those places. It does not say which side is right; every difference is checked against the wiki page::

    python -m trioforge.reports.eqltools_diff --catalog derived/catalog.json \\
        --eqltools sources/eqltools/gear-data-2026-10-11.json --out reports/eqltools-diff-2026-10-14.md

**Matching.** Items are matched by :func:`match_key` of their name: lowercase, accents and apostrophes dropped,
a leading "a", "an" or "the" ignored, ``*`` read as the word "star" (EQL Tools lists both "Club" and "Club*"),
every other run of punctuation one space. A name that several items share on either side is *ambiguous* and is
not compared.

**Fields.** For every matched pair, each field below is counted ``equal``, ``different``, ``missing_ours`` (EQL
Tools has a value and the catalog has none) or ``missing_theirs``; a field neither side has is not counted. A
stat of 0 is no value, as in the catalog. EQL Tools' short keys: ``n`` the name, ``sl`` the slots, ``cls`` the
classes (``{"all": 1}``, ``{"all": 1, "x": [excluded]}`` or ``{"c": [listed]}``), ``st`` the stats in lower case
(the haste is the top-level ``haste``), ``sv`` the resists (``f c m p d`` and ``v`` for Void), ``wt`` the weight,
``era`` the era tag, ``oe`` the out-of-era flag and ``t`` the wiki page title.

=========  ==========================================================================================
slots      the same set of canonical slot names (EQL Tools writes "Fingers" for FINGER)
classes    the same set of class codes (``ALL`` is all sixteen)
stats.*    AC STR STA AGI DEX WIS INT CHA HP MANA END ATK HASTE (EQL Tools has no regeneration stats)
sv.*       FIRE COLD MAGIC POISON DISEASE and VOID (the catalog has no Void resist)
weight     the same number
era        EQL Tools' era tag is one of the catalog's, ignoring case
oe         EQL Tools' out-of-era flag against the evidence level: ``hidden`` and ``disputed`` count as
           out of era (a cross-tabulation by level and a count of our reason codes follow)
=========  ==========================================================================================

Up to 20 examples are kept for every list, in name order (the report prints those of what differs), and the
report is the same bytes for the same input. Every name from the two files is sanitized and written as a code span, because the
source is wiki text, which is hostile input.

**Nothing from a seen-in-game build is used.** The report is public and those flags are private. :func:`diff`
refuses any input that carries the code ``seen-in-game`` anywhere in it (a reason of the catalog in any shape,
a name, a key), :func:`render_markdown` refuses a result that would print it, and the file readers refuse a file
whose text mentions it at all, in any case or spelled with a JSON escape. The refusal is one line and names
no item.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
import urllib.parse
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import trioforge
from trioforge.classes import CLASS_CODES
from trioforge.data.evidence import era_key
from trioforge.data.jsonio import MAX_FILE_BYTES, JsonFileError, load_strict
from trioforge.data.normalize import SLOTS, STAT_KEYS, sanitize_text
from trioforge.sources.client_tables import commit_files, iso_date, one_line, today_utc

__all__ = [
    "CREDIT",
    "EXAMPLES",
    "FIELD_ORDER",
    "GENERATOR",
    "INPUT_LICENSE",
    "diff",
    "main",
    "match_key",
    "norm_name",
    "read_catalog",
    "read_eqltools",
    "render_markdown",
]

INPUT_LICENSE = "CC BY-SA 4.0"
SEEN_CODE = "seen-in-game"  # the code of the private flags; this report is public and must never carry it
CREDIT = "EQL Tools (eqltools.com), gear data CC BY-SA 4.0, used as a cross-check"
GENERATOR = f"trioforge.reports.eqltools_diff {trioforge.__version__}"
EXAMPLES = 20  # examples kept for every list
CATEGORIES = ("equal", "different", "missing_ours", "missing_theirs")
PRINTED = CATEGORIES[1:]  # the report prints the examples of what differs; the equal ones stay in the data
OUT_OF_ERA_LEVELS = ("hidden", "disputed")  # our evidence levels that mean "not in EQL" for the oe field
LEVEL_COLUMNS = ("strict", "wiki", "disputed", "hidden", "none")
DISAGREEMENTS = ("ours out of era, EQL Tools in era", "ours in era, EQL Tools out of era")

# ---- the name matching ------------------------------------------------------------------------------

# Apostrophes, the backtick, curly quotes and the replacement character that a mis-decoded apostrophe leaves.
_QUOTES = "`'" + "".join(chr(code) for code in (0x2018, 0x2019, 0x201B, 0x2032, 0xB4, 0xFFFD))
_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_ARTICLE = re.compile(r"^(?:a|an|the) ")
# Two spellings the sources disagree on: a typo the wiki and the game spell differently, and a page title that
# carries a disambiguation the game name lacks.
_NAME_ALIASES = {
    "deterioriated ancient faydark longbow": "deteriorated ancient faydark longbow",
    "tenderizer weapon": "tenderizer",
}


def norm_name(text: Any) -> str:
    """Lowercase, accents and apostrophes dropped, ``*`` as the word "star", other punctuation as one space."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    lowered = "".join(char for char in decomposed if not unicodedata.combining(char)).lower()
    unquoted = "".join(char for char in lowered if char not in _QUOTES).replace("*", " star ")
    return " ".join(_NOT_ALPHANUMERIC.sub(" ", unquoted).split())


def match_key(text: Any) -> str:
    """The key two records must share to be the same item: :func:`norm_name` without a leading article, plus the
    two known spelling aliases."""
    key = _ARTICLE.sub("", norm_name(text))
    return _NAME_ALIASES.get(key, key)


# ---- reading values from the two sides ----------------------------------------------------------------

_ALL_CLASSES = frozenset(CLASS_CODES)
_SLOT_ORDER = {slot: position for position, slot in enumerate(SLOTS)}
_SLOT_ALIASES = {"FINGERS": "FINGER", "EARS": "EAR", "WRISTS": "WRIST", "SHOULDER": "SHOULDERS"}
_STAT_FIELDS = tuple(stat for stat in STAT_KEYS if stat not in ("HPREG", "MANAREG", "ENDREG"))  # EQL Tools has none
_SV_LETTERS = {"FIRE": "f", "COLD": "c", "MAGIC": "m", "POISON": "p", "DISEASE": "d", "VOID": "v"}


def _number(value: Any) -> int | float | None:
    """A JSON number as an int (when whole) or a float rounded to 4 places; anything else is None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        value = round(value, 4)
        if value == int(value):
            return int(value)
    return value


def _stat(value: Any) -> int | float | None:
    """A stat: a number, and 0 is no value (zeros are omitted on both sides)."""
    return _number(value) or None


def _codes(values: Any) -> set[str]:
    if not isinstance(values, (list, tuple)):
        return set()
    return {value.strip().upper() for value in values if isinstance(value, str) and value.strip()}


def _slot(name: str) -> str:
    upper = name.strip().upper()
    return _SLOT_ALIASES.get(upper, upper)


def _slot_set(values: Any) -> frozenset[str] | None:
    if not isinstance(values, (list, tuple)):
        return None
    return frozenset(_slot(value) for value in values if isinstance(value, str) and value.strip()) or None


def _show_slots(slots: frozenset[str]) -> str:
    return " ".join(sorted(slots, key=lambda slot: (_SLOT_ORDER.get(slot, len(_SLOT_ORDER)), slot)))


def _our_classes(item: Mapping[str, Any]) -> frozenset[str] | None:
    classes = item.get("classes")
    if not isinstance(classes, (list, tuple)):
        return None
    codes = _codes(classes)
    return _ALL_CLASSES if "ALL" in codes else frozenset(codes)


def _their_classes(record: Mapping[str, Any]) -> frozenset[str] | None:
    classes = record.get("cls")
    if not isinstance(classes, Mapping):
        return None
    if classes.get("all"):
        return frozenset(_ALL_CLASSES - _codes(classes.get("x")))
    if "c" in classes:
        return frozenset(_codes(classes["c"]))
    return None


def _show_classes(codes: frozenset[str]) -> str:
    if codes == _ALL_CLASSES:
        return "ALL"
    if not codes:
        return "NONE"
    return " ".join(sorted(codes, key=lambda code: (CLASS_CODES.index(code) if code in CLASS_CODES else len(CLASS_CODES), code)))


def _our_stat(stat: str) -> Callable[[Mapping[str, Any]], int | float | None]:
    def read(item: Mapping[str, Any]) -> int | float | None:
        stats = item.get("stats")
        return _stat(stats.get(stat)) if isinstance(stats, Mapping) else None

    return read


def _their_stat(stat: str) -> Callable[[Mapping[str, Any]], int | float | None]:
    def read(record: Mapping[str, Any]) -> int | float | None:
        stats = record.get("st")
        if stat == "HASTE":  # EQL Tools keeps the worn haste beside the stats, not in them
            value = record.get("haste")
            if value is None and isinstance(stats, Mapping):
                value = stats.get("haste")
            return _stat(value)
        return _stat(stats.get(stat.lower())) if isinstance(stats, Mapping) else None

    return read


def _our_resist(school: str) -> Callable[[Mapping[str, Any]], int | float | None]:
    def read(item: Mapping[str, Any]) -> int | float | None:
        resists = item.get("sv")
        return _stat(resists.get(school)) if isinstance(resists, Mapping) else None

    return read


def _their_resist(school: str) -> Callable[[Mapping[str, Any]], int | float | None]:
    def read(record: Mapping[str, Any]) -> int | float | None:
        resists = record.get("sv")
        return _stat(resists.get(_SV_LETTERS[school])) if isinstance(resists, Mapping) else None

    return read


def _our_eras(item: Mapping[str, Any]) -> tuple[str, ...] | None:
    tags = item.get("era_tags")
    if not isinstance(tags, (list, tuple)):
        return None
    return tuple(tag for tag in tags if isinstance(tag, str) and era_key(tag)) or None


def _their_eras(record: Mapping[str, Any]) -> tuple[str, ...] | None:
    era = record.get("era")
    return (era,) if isinstance(era, str) and era_key(era) else None


def _same_era(ours: tuple[str, ...], theirs: tuple[str, ...]) -> bool:
    return {era_key(tag) for tag in theirs} <= {era_key(tag) for tag in ours}


def _show_eras(tags: tuple[str, ...]) -> str:
    return ", ".join(sanitize_text(tag) or "" for tag in tags)


def _reason_kinds(reasons: Any) -> tuple[str, ...]:
    """The distinct reason codes, sorted, each cut at its first colon ("live-source:Some Zone" is "live-source")."""
    kinds: set[str] = set()
    if isinstance(reasons, (list, tuple)):
        for reason in reasons:
            code = reason.get("code") if isinstance(reason, Mapping) else None
            if isinstance(code, str) and code:
                kinds.add(code.split(":", 1)[0])
    return tuple(sorted(kinds))


def _our_evidence(item: Mapping[str, Any]) -> tuple[str, tuple[str, ...]] | None:
    """Our evidence level and the kinds of reason behind it, or None if the item carries no evidence."""
    evidence = item.get("evidence")
    level = evidence.get("level") if isinstance(evidence, Mapping) else None
    if not isinstance(level, str) or not level:
        return None
    return level, _reason_kinds(evidence.get("reasons"))


def _their_out_of_era(record: Mapping[str, Any]) -> bool:
    return bool(record.get("oe"))


def _same_flag(evidence: tuple[str, tuple[str, ...]], out_of_era: bool) -> bool:
    return (evidence[0] in OUT_OF_ERA_LEVELS) == out_of_era


def _show_evidence(evidence: tuple[str, tuple[str, ...]]) -> str:
    level, kinds = evidence
    return f"{level} ({', '.join(kinds)})" if kinds else level


@dataclass(frozen=True)
class _Field:
    """One compared field: how to read it on each side, when two values are the same, how to show them."""

    name: str
    label: str
    ours: Callable[[Mapping[str, Any]], Any]
    theirs: Callable[[Mapping[str, Any]], Any]
    same: Callable[[Any, Any], bool]
    show_ours: Callable[[Any], Any]
    show_theirs: Callable[[Any], Any]


def _plain(value: Any) -> Any:
    return value


def _equal(ours: Any, theirs: Any) -> bool:
    return bool(ours == theirs)


def _build_fields() -> tuple[_Field, ...]:
    fields = [
        _Field("slots", "slots", lambda item: _slot_set(item.get("slots")), lambda record: _slot_set(record.get("sl")), _equal, _show_slots, _show_slots),
        _Field("classes", "classes", _our_classes, _their_classes, _equal, _show_classes, _show_classes),
    ]
    for stat in _STAT_FIELDS:
        fields.append(_Field(f"stats.{stat}", stat, _our_stat(stat), _their_stat(stat), _equal, _plain, _plain))
    for school in _SV_LETTERS:
        fields.append(_Field(f"sv.{school}", f"SV {school}", _our_resist(school), _their_resist(school), _equal, _plain, _plain))
    fields.append(
        _Field("weight", "weight", lambda item: _number(item.get("weight")), lambda record: _number(record.get("wt")), _equal, _plain, _plain)
    )
    fields.append(_Field("era", "era", _our_eras, _their_eras, _same_era, _show_eras, _show_eras))
    fields.append(
        _Field(
            "oe",
            "out of era (oe)",
            _our_evidence,
            _their_out_of_era,
            _same_flag,
            _show_evidence,
            lambda out_of_era: "out of era" if out_of_era else "in era",
        )
    )
    return tuple(fields)


_FIELDS = _build_fields()
FIELD_ORDER = tuple(field.name for field in _FIELDS)


# ---- the diff -------------------------------------------------------------------------------------------------


def _holds_seen_code(data: Any) -> bool:
    """Whether any string in this JSON-like data, a key or a value at any depth, holds the code of a seen flag
    (in any case)."""
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            if SEEN_CODE in node.casefold():
                return True
        elif isinstance(node, Mapping):
            for key, value in node.items():
                stack.append(key)
                stack.append(value)
        elif isinstance(node, (list, tuple, set, frozenset)):
            stack.extend(node)
    return False


def _seen_refusal(what: str) -> ValueError:
    return ValueError(f"{what} carries {SEEN_CODE} flags; a public report is made only from the committed catalog, which has none")


def _gear_records(eqltools_json: Any) -> list[Any]:
    """The records of an EQL Tools file: its ``items`` (a dict keyed by lookup key, or a list), or a bare list."""
    items = eqltools_json.get("items") if isinstance(eqltools_json, Mapping) else eqltools_json
    if isinstance(items, Mapping):
        return list(items.values())
    if isinstance(items, (list, tuple)):
        return list(items)
    raise ValueError("the EQL Tools data has no items (a dict or a list of records)")


def _group(entries: Iterable[Any], name_field: str) -> tuple[dict[str, list[Mapping[str, Any]]], int]:
    """The readable entries grouped by name key, and the number of entries that could not be read."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    unreadable = 0
    for entry in entries:
        name = entry.get(name_field) if isinstance(entry, Mapping) else None
        key = match_key(name) if isinstance(name, str) else ""
        if not key:
            unreadable += 1
            continue
        groups.setdefault(key, []).append(entry)
    return groups, unreadable


def _clean(value: Any) -> str:
    return sanitize_text(str(value)) or ""


def _our_name(item: Mapping[str, Any]) -> str:
    return _clean(item["name"])


def _our_key(item: Mapping[str, Any]) -> str | None:
    key = item.get("key")
    return (_clean(key) or None) if isinstance(key, str) else None


def _their_page(record: Mapping[str, Any]) -> str:
    title = record.get("t")  # EQL Tools writes the wiki title with underscores and %XX escapes
    page = _clean(urllib.parse.unquote(title.replace("_", " "))) if isinstance(title, str) else ""
    return page or _clean(record["n"])


def diff(catalog_items: Iterable[Any], eqltools_json: Any, *, examples: int = EXAMPLES) -> dict[str, Any]:
    """Compare the catalog's items with an EQL Tools gear file (see the module docstring).

    Returns plain JSON data: ``limit`` (the number of examples kept per list), ``totals`` (items on each side,
    matched, ambiguous, only on one side, unreadable), ``fields`` (for each of :data:`FIELD_ORDER`: the four
    counts and up to ``limit`` examples of each of the four),
    ``oe_by_level`` (EQL Tools' flag against our evidence level), ``oe_by_reason`` (for the pairs that disagree
    about out of era, how many times each of our reason codes occurs) and ``examples`` (``only_ours_wearable``,
    ``only_theirs`` and ``ambiguous``). Neither input is changed. Raises :class:`ValueError` if the EQL Tools
    data has no items, and if either input carries a ``seen-in-game`` flag anywhere (a reason in any shape, a
    name, a key): the report is public and those flags are private, so no report is made from them.
    """
    limit = max(0, int(examples))
    catalog_items = list(catalog_items)
    if _holds_seen_code(catalog_items) or _holds_seen_code(eqltools_json):
        raise _seen_refusal("the data")
    records = _gear_records(eqltools_json)
    ours_groups, unreadable_ours = _group(catalog_items, "name")
    theirs_groups, unreadable_theirs = _group(records, "n")

    fields: dict[str, dict[str, Any]] = {
        field.name: {
            **{category: 0 for category in CATEGORIES},
            "examples": {category: [] for category in CATEGORIES},
        }
        for field in _FIELDS
    }
    crosstab = {row: {column: 0 for column in LEVEL_COLUMNS} for row in ("out of era", "in era")}
    by_reason: dict[str, Counter[str]] = {side: Counter() for side in DISAGREEMENTS}
    kept: dict[str, list[dict[str, Any]]] = {"only_ours_wearable": [], "only_theirs": [], "ambiguous": []}
    totals = {
        "ours": sum(len(group) for group in ours_groups.values()),
        "theirs": sum(len(group) for group in theirs_groups.values()),
        "matched": 0,
        "ambiguous": 0,
        "ambiguous_ours": 0,
        "ambiguous_theirs": 0,
        "only_ours": 0,
        "only_ours_wearable": 0,
        "only_theirs": 0,
        "unreadable_ours": unreadable_ours,
        "unreadable_theirs": unreadable_theirs,
    }

    for name_key in sorted(ours_groups.keys() | theirs_groups.keys()):
        mine = sorted(ours_groups.get(name_key, []), key=lambda item: str(item.get("key") or ""))
        theirs = sorted(theirs_groups.get(name_key, []), key=lambda record: (_their_page(record), _clean(record["n"])))
        if mine and theirs:
            if len(mine) == 1 and len(theirs) == 1:
                totals["matched"] += 1
                _compare_pair(mine[0], theirs[0], fields, crosstab, by_reason, limit)
            else:
                totals["ambiguous"] += 1
                totals["ambiguous_ours"] += len(mine)
                totals["ambiguous_theirs"] += len(theirs)
                if len(kept["ambiguous"]) < limit:
                    kept["ambiguous"].append(
                        {
                            "name": _our_name(mine[0]),
                            "ours": [key for key in (_our_key(item) for item in mine) if key],
                            "theirs": sorted({_their_page(record) for record in theirs}),
                        }
                    )
        elif mine:
            for item in mine:
                totals["only_ours"] += 1
                if _slot_set(item.get("slots")):
                    totals["only_ours_wearable"] += 1
                    if len(kept["only_ours_wearable"]) < limit:
                        kept["only_ours_wearable"].append({"key": _our_key(item), "name": _our_name(item)})
        else:
            for record in theirs:
                totals["only_theirs"] += 1
                if len(kept["only_theirs"]) < limit:
                    kept["only_theirs"].append({"name": _clean(record["n"]), "page": _their_page(record)})

    ordered = {side: dict(sorted(found.items(), key=lambda entry: (-entry[1], entry[0]))) for side, found in by_reason.items()}
    return {
        "limit": limit,
        "totals": totals,
        "fields": fields,
        "oe_by_level": crosstab,
        "oe_by_reason": ordered,
        "examples": kept,
    }


def _compare_pair(
    item: Mapping[str, Any],
    record: Mapping[str, Any],
    fields: dict[str, dict[str, Any]],
    crosstab: dict[str, dict[str, int]],
    by_reason: dict[str, Counter[str]],
    limit: int,
) -> None:
    for field in _FIELDS:
        ours = field.ours(item)
        theirs = field.theirs(record)
        if ours is None and theirs is None:
            continue
        if ours is None:
            category = "missing_ours"
        elif theirs is None:
            category = "missing_theirs"
        else:
            category = "equal" if field.same(ours, theirs) else "different"
        result = fields[field.name]
        result[category] += 1
        if len(result["examples"][category]) < limit:
            result["examples"][category].append(
                {
                    "key": _our_key(item),
                    "name": _our_name(item),
                    "ours": None if ours is None else field.show_ours(ours),
                    "theirs": None if theirs is None else field.show_theirs(theirs),
                }
            )
    evidence = _our_evidence(item)
    level = evidence[0] if evidence else None
    their_out = _their_out_of_era(record)
    crosstab["out of era" if their_out else "in era"][level if level in LEVEL_COLUMNS[:-1] else "none"] += 1
    if evidence and (level in OUT_OF_ERA_LEVELS) != their_out:
        side = DISAGREEMENTS[1] if their_out else DISAGREEMENTS[0]
        by_reason[side].update(evidence[1] or ("none",))


# ---- the report ---------------------------------------------------------------------------------------------------

_BACKTICK_RUN = re.compile(r"`+")


def _code(value: Any) -> str:
    """Text as a Markdown code span, so that nothing in it is markup: sanitized first (no angle brackets, no
    control or invisible characters, one line), with a fence longer than any backtick run inside."""
    text = _clean(value)
    if not text:
        return "(empty)"
    fence = "`" * (max((len(run) for run in _BACKTICK_RUN.findall(text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _shown(value: Any) -> str:
    return "none" if value is None else _code(value)


def _label(field: str) -> str:
    for known in _FIELDS:
        if known.name == field:
            return known.label
    return field


def _example_line(example: Mapping[str, Any]) -> str:
    key = example.get("key")
    head = f"- {_code(example.get('name'))}" + (f" ({_code(key)})" if key else "")
    return f"{head}: ours {_shown(example.get('ours'))}, theirs {_shown(example.get('theirs'))}"


def _reason_table(by_reason: Mapping[str, Mapping[str, int]]) -> list[str]:
    """The table of our reason codes where the two sources disagree about out of era (nothing if they never do)."""
    found = {side: dict(by_reason.get(side) or {}) for side in DISAGREEMENTS}
    codes = sorted(
        {code for counts in found.values() for code in counts},
        key=lambda code: (-sum(counts.get(code, 0) for counts in found.values()), code),
    )
    if not codes:
        return []
    lines = [
        "",
        "## Out of era disagreements by reason",
        "",
        "For the matched pairs that disagree about out of era, how many times each of our reason codes occurs. An "
        "item counts once for every reason code it carries.",
        "",
        f"| reason | {DISAGREEMENTS[0]} | {DISAGREEMENTS[1]} |",
        "|---|---:|---:|",
    ]
    for code in codes:
        lines.append(f"| {_code(code)} | {found[DISAGREEMENTS[0]].get(code, 0)} | {found[DISAGREEMENTS[1]].get(code, 0)} |")
    return lines


def _only_theirs_line(example: Mapping[str, Any]) -> str:
    name, page = example.get("name"), example.get("page")
    return f"- {_code(name)}" + (f" (page {_code(page)})" if page != name else "")


def _only_ours_line(example: Mapping[str, Any]) -> str:
    key = example.get("key")
    return f"- {_code(example.get('name'))}" + (f" ({_code(key)})" if key else "")


def _ambiguous_line(example: Mapping[str, Any]) -> str:
    ours = ", ".join(_code(key) for key in example.get("ours", [])) or "none"
    theirs = ", ".join(_code(page) for page in example.get("theirs", [])) or "none"
    return f"- {_code(example.get('name'))}: ours {ours}; EQL Tools {theirs}"


def render_markdown(d: Mapping[str, Any]) -> str:
    """The report for a :func:`diff` result as Markdown (the same bytes for the same data).

    If ``d["meta"]`` is present (the command line adds it) the report also names the inputs by file name and
    sha256; no folder of this machine is ever written.
    """
    totals = d["totals"]
    meta = d.get("meta")
    out: list[str] = ["# EQL Tools cross-check", ""]
    if isinstance(meta, Mapping):
        out += [f"Generated {_clean(meta.get('generated'))} by {_clean(meta.get('generator'))}.", ""]
    out += [
        "EQL Tools publishes a gear list compiled from the same wiki pages as our catalog. A difference below "
        "means that one of the two parsers read a page differently, or that one of them skipped it. Nothing "
        "here says which side is right: each difference has to be checked against the wiki page.",
        "",
        f"Credit: {CREDIT}. EQL Tools compiled its data from eqlwiki (https://eqlwiki.com/), CC BY-SA 4.0. "
        "Our side of the comparison is item data adapted from eqlwiki.com (CC BY-SA 4.0) by the eqlwiki "
        "contributors. This report is released under CC BY-SA 4.0.",
        "",
    ]
    if isinstance(meta, Mapping):
        catalog = meta.get("catalog") if isinstance(meta.get("catalog"), Mapping) else {}
        gear = meta.get("eqltools") if isinstance(meta.get("eqltools"), Mapping) else {}
        out += [
            "## Inputs",
            "",
            "| input | file | sha256 | note |",
            "|---|---|---|---|",
            f"| TrioForge catalog | {_code(catalog.get('file'))} | {_code(catalog.get('sha256'))} | version {_shown(catalog.get('version'))} |",
            f"| EQL Tools gear data | {_code(gear.get('file'))} | {_code(gear.get('sha256'))} | licence {_code(gear.get('license'))} |",
            "",
        ]
    out += [
        "## How items are matched",
        "",
        "Items are matched by name: lowercase, accents and apostrophes dropped, a leading \"a\", \"an\" or "
        "\"the\" ignored, `*` read as the word star, every other run of punctuation as one space. A name that "
        "several items share on either side is not compared; the shared names are listed below.",
        "",
        "## Items",
        "",
        "| | items |",
        "|---|---:|",
        f"| Items in our catalog | {totals['ours']} |",
        f"| Items in EQL Tools' gear data | {totals['theirs']} |",
        f"| Matched one to one by name | {totals['matched']} |",
        f"| Names shared by several items, not compared | {totals['ambiguous']} |",
        f"| Our items in those names | {totals['ambiguous_ours']} |",
        f"| EQL Tools items in those names | {totals['ambiguous_theirs']} |",
        f"| Only in our catalog | {totals['only_ours']} |",
        f"| Only in our catalog, with a slot | {totals['only_ours_wearable']} |",
        f"| Only in EQL Tools | {totals['only_theirs']} |",
        f"| Entries that could not be read, our catalog | {totals['unreadable_ours']} |",
        f"| Entries that could not be read, EQL Tools | {totals['unreadable_theirs']} |",
        "",
        "## Fields",
        "",
        "Compared: slots, classes, the stats EQL Tools carries (it has no regeneration stats), the resists "
        "(including Void, which only EQL Tools has), weight, era and the out-of-era flag. Not compared: races, "
        "deities, flags, weapon data, effects and sources.",
        "",
        "Counted over the matched pairs. equal: both sides have a value and it is the same. different: both "
        "have a value and they differ. missing-ours: EQL Tools has a value and our catalog has none. "
        "missing-theirs: our catalog has a value and EQL Tools has none. A field neither side has is not "
        "counted, and a stat of 0 is no value.",
        "",
        "| field | equal | different | missing-ours | missing-theirs |",
        "|---|---:|---:|---:|---:|",
    ]
    fields = d["fields"]
    for name, result in fields.items():
        out.append(
            f"| {_clean(_label(name))} | {result['equal']} | {result['different']} | "
            f"{result['missing_ours']} | {result['missing_theirs']} |"
        )
    out += [
        "",
        "The out-of-era row compares EQL Tools' `oe` flag with our evidence level, where hidden and disputed "
        "count as out of era.",
        "",
        "## Out of era against our evidence level",
        "",
        "| EQL Tools says | strict | wiki | disputed | hidden | no evidence |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row, columns in d["oe_by_level"].items():
        out.append(f"| {_clean(row)} | " + " | ".join(str(columns.get(column, 0)) for column in LEVEL_COLUMNS) + " |")
    out += _reason_table(d.get("oe_by_reason") or {})
    out += ["", "## Examples", "", f"Up to {d.get('limit', EXAMPLES)} for each list, in name order.", ""]
    kept = d["examples"]
    sections: list[tuple[str, list[str]]] = [
        ("Only in EQL Tools", [_only_theirs_line(e) for e in kept["only_theirs"]]),
        ("Only in our catalog, with a slot", [_only_ours_line(e) for e in kept["only_ours_wearable"]]),
        ("Names shared by several items", [_ambiguous_line(e) for e in kept["ambiguous"]]),
    ]
    for name, result in fields.items():
        for category in PRINTED:
            if result["examples"][category]:
                title = f"{_clean(_label(name))}: {category.replace('_', '-')}"
                sections.append((title, [_example_line(e) for e in result["examples"][category]]))
    for title, lines in sections:
        if lines:
            out += [f"### {title}", "", *lines, ""]
    text = "\n".join(out).rstrip("\n") + "\n"
    if SEEN_CODE in text.casefold():  # a result put together by hand; diff() never gives one
        raise _seen_refusal("the report")
    return text


# ---- reading the two files -----------------------------------------------------------------------------------------


def _load(path: str | Path) -> Any:
    """The strict JSON of a file. A file whose text holds the code of a seen flag anywhere, however it is spelled
    (in any case, or with a JSON escape), is refused before it is used: the report is public."""
    source = Path(path)
    with source.open("rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    if SEEN_CODE in raw.decode("utf-8", "replace").casefold():
        raise ValueError(f"{source.name}: the file mentions {SEEN_CODE} flags; a public report is made only from the committed catalog, which has none")
    try:
        document = load_strict(source)
    except JsonFileError as error:
        raise ValueError(str(error)) from error
    if _holds_seen_code(document):  # spelled with escapes in the text
        raise ValueError(f"{source.name}: the file mentions {SEEN_CODE} flags; a public report is made only from the committed catalog, which has none")
    return document


def read_catalog(path: str | Path) -> dict[str, Any]:
    """The catalog document (``{"version", ..., "items": [...]}``) of a catalog file.

    Raises :class:`ValueError` (a one-line message, no file content) if the file is not strict JSON, has no
    list of items, or its text mentions ``seen-in-game`` anywhere: the report is public and those flags are
    private.
    """
    source = Path(path)
    document = _load(source)
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"{source.name}: no list of items")
    return document


def read_eqltools(path: str | Path) -> dict[str, Any]:
    """The EQL Tools gear document of a file.

    Raises :class:`ValueError` (a one-line message, no file content) if the file is not strict JSON, does not
    declare the licence CC BY-SA 4.0, has no items, or its text mentions ``seen-in-game`` anywhere.
    """
    source = Path(path)
    document = _load(source)
    meta = document.get("meta") if isinstance(document, dict) else None
    if not isinstance(meta, dict) or meta.get("license") != INPUT_LICENSE:
        raise ValueError(f"{source.name}: the file does not declare the licence {INPUT_LICENSE}; it is not used")
    items = document.get("items")
    if not isinstance(items, (dict, list)) or not items:
        raise ValueError(f"{source.name}: no items")
    return document


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _count(number: int, singular: str, plural: str | None = None) -> str:
    return f"{number} {singular if number == 1 else plural or singular + 's'}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.reports.eqltools_diff",
        description="Compare the catalog with EQL Tools' gear data and write the differences as a Markdown report.",
    )
    parser.add_argument("--catalog", required=True, type=Path, help="derived/catalog.json (a build without seen flags)")
    parser.add_argument("--eqltools", required=True, type=Path, help="EQL Tools gear JSON (sources/eqltools/...)")
    parser.add_argument("--out", type=Path, help="report file (default: reports/eqltools-diff-<date>.md)")
    parser.add_argument("--date", type=iso_date, help="generation date, YYYY-MM-DD (default: today in UTC)")
    args = parser.parse_args(argv)
    generated = args.date or today_utc()
    out = args.out or Path("reports") / f"eqltools-diff-{generated}.md"
    try:
        catalog = read_catalog(args.catalog)
        gear = read_eqltools(args.eqltools)
        result = diff(catalog["items"], gear)
        version = catalog.get("version")
        result["meta"] = {
            "generated": generated,
            "generator": GENERATOR,
            "catalog": {"file": args.catalog.name, "sha256": _sha256(args.catalog), "version": version if isinstance(version, str) else None},
            "eqltools": {"file": args.eqltools.name, "sha256": _sha256(args.eqltools), "license": INPUT_LICENSE},
        }
        commit_files(out.parent, {out.name: render_markdown(result)}, last=out.name)
    except (OSError, ValueError) as error:
        print(f"error: {one_line(error)}", file=sys.stderr)
        return 2
    totals = result["totals"]
    differing = [name for name, field in result["fields"].items() if field["different"] or field["missing_ours"] or field["missing_theirs"]]
    values = sum(
        field["different"] + field["missing_ours"] + field["missing_theirs"] for field in result["fields"].values()
    )
    print(
        f"{out.name}: {totals['matched']} matched, {_count(totals['ambiguous'], 'shared name')}, "
        f"{totals['only_theirs']} only in EQL Tools, {totals['only_ours']} only in our catalog "
        f"({totals['only_ours_wearable']} with a slot), {_count(values, 'difference')} in {_count(len(differing), 'field')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
