"""Reports from players: the list of items they say they saw in game.

``rules/community-seen.json`` is the one place where what players say reaches the evidence ladder (:func:`trioforge.data.evidence.classify`: a reported item is strict,
unless the wiki itself says the item is gone), so it is built to hold nothing that could name a player::

    {"version": "2026-10-18",
     "reports":   [{"key": "w123", "kind": "seen", "issue": 5, "date": "2026-10-18", "check": "item-window-screenshot"}],
     "retracted": [{"key": "w456", "issue": 7, "date": "2026-10-19", "reason": "withdrawn"}]}

* **No free text and no link.** Every field is a key, a number, a day or a word from a fixed list, and a field that is not listed here is refused. The address of an
  issue is built from the owner of the build (``https://github.com/<owner>/trioforge/issues/<n>``) and never stored.
* ``key`` is ``w`` and the number of the wiki page of an item of the public catalog (the catalog has no other key, and a slug could hold a sentence). ``kind`` says what the
  report is: ``seen`` (the item) or ``tier`` (a tier of it). ``issue`` is the number of the issue where it was reported, a whole number from 1. ``date`` is the day it was
  accepted (a retraction: the day it was made), in UTC, and never a day after today. ``check`` is ``item-window-screenshot``: a report counts only when a maintainer has checked
  a screenshot of the item window. ``reason`` is one of ``withdrawn``, ``wrong-item``, ``rejected`` and ``duplicate``; the list holds no word that says what the person did,
  because a reason stays in a public file beside an issue number for good.
* An item and an issue appear once in the file, and **an issue is in one list only**: a retraction moves every entry of the issue, and a retracted issue takes no new report,
  of the same item or of another (a new report is a new issue). The entries of ``retracted`` give no key: they are the record of what was taken back.
* The file is written sorted (by key as text, as the catalog is, and then by issue), one entry to a line, so that a change shows as the lines it changed.

The reader, :func:`read_document`, is the one the catalog builder uses (:func:`trioforge.data.catalog.load_community_keys`). It refuses anything the form does not allow, a
repeated item and issue, and a file of the old form (a link for the issue) with a line that says how to convert it. An error is one line and never repeats what the file said.

**The command** keeps the file::

    python -m trioforge.community add --key w123 --issue 5 --kind seen --screenshot-checked
    python -m trioforge.community retract --issue 5 --reason withdrawn

* ``add`` records one report. ``--screenshot-checked`` is required, and says that a maintainer has checked a screenshot of the item window (a report counts only then). The key
  must be a wearable of ``derived/catalog.json`` (an item that lists a slot of a place of a kit). The day is today in UTC. A second report of the same item and issue is refused,
  and so is any report for an issue that was retracted.
* ``retract`` moves every entry of an issue from ``reports`` to ``retracted`` with a reason from the list and the day. An issue nobody reported is refused.
* Every write is atomic (the whole file is replaced or none of it) and keeps the file sorted. The command prints the entry it made or moved, as it is written in the file, and
  the counts (``reports N, retracted M``), and nothing else. A refusal is one line on standard error, ``error: ...``, exit status 2, and the file as it was.
* The command needs no privacy key: the file and the output hold keys, numbers, days and words from the lists, and the hooks that scan a commit check them.

The address of an issue is built from the owner of the build, never stored: :func:`issue_url`.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from trioforge.data.jsonio import JsonFileError, load_strict, render
from trioforge.model.items import SLOT_GROUPS
from trioforge.sources.client_tables import commit_files, today_utc

__all__ = [
    "CHECKS",
    "KINDS",
    "MAX_ISSUE",
    "REASONS",
    "RELATIVE_PATH",
    "REPORT_FIELDS",
    "REPOSITORY",
    "RETRACTED_FIELDS",
    "WEARABLE_SLOTS",
    "CommunityError",
    "add_report",
    "check_document",
    "issue_url",
    "main",
    "read_document",
    "render_document",
    "retract_issue",
    "sorted_entries",
]

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests point this at a scratch folder
RELATIVE_PATH = "rules/community-seen.json"
CATALOG_PATH = "derived/catalog.json"
REPOSITORY = "trioforge"  # the name of the project's repository; the account that owns it is the owner of the build
KINDS = ("seen", "tier")
CHECKS = ("item-window-screenshot",)
REASONS = ("withdrawn", "wrong-item", "rejected", "duplicate")  # (a reason stays in a public file beside an issue number: none says what the person did)
MAX_ISSUE = 999_999_999  # the numbers of GitHub's issues are far below this; a longer one is a typing mistake
TOP_FIELDS = ("version", "reports", "retracted")

#: the slots an item must list to be a wearable of a kit (the same groups as ``trioforge.precompute.grid.WEARABLE_SLOTS``, which has heavier imports)
WEARABLE_SLOTS = frozenset(name for name, _ in SLOT_GROUPS)

#: the key of an item that has a wiki page: w and the number of the page. The public catalog has no other (an item without a page has a slug for a key, and a slug is a field
#: that could hold a sentence), so no other is a key of a report.
_KEY = re.compile(r"w[0-9]{1,15}")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ISSUE_ARGUMENT = re.compile(r"[1-9][0-9]{0,8}")  # as the command line writes an issue: digits, no sign, no leading zero, at most MAX_ISSUE
#: a GitHub account name: letters, digits and single hyphens, no hyphen at either end, 39 characters at most (the site build holds the owner to the same form)
_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
PLACEHOLDER_OWNER = "owner"  # the word the repository files use until the project has an account: a real account of someone else

OLD_FORM = (
    f"{RELATIVE_PATH} is in the old form (a report with a link for its issue, and no kind, date or check): convert it by hand, keeping a report only when a maintainer "
    'has checked a screenshot of its item window, to {"key", "kind": "seen", "issue": <the number at the end of the link>, "date", "check": "item-window-screenshot"}, '
    'and add "retracted": []'
)


class CommunityError(ValueError):
    """The list of reports is damaged or in the old form, or a command was refused. The message is one line and never repeats what the file said."""


def _day(value: Any) -> bool:
    if not isinstance(value, str) or _DAY.fullmatch(value) is None:
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _key(value: Any) -> bool:
    return isinstance(value, str) and _KEY.fullmatch(value) is not None


def _issue(value: Any) -> bool:
    return type(value) is int and 1 <= value <= MAX_ISSUE  # (not a bool, not 5.0)


def _one_of(allowed: tuple[str, ...]):
    return lambda value: isinstance(value, str) and value in allowed


#: the fields of an entry in the order they are written, each with what it must be
REPORT_FIELDS = {"key": _key, "kind": _one_of(KINDS), "issue": _issue, "date": _day, "check": _one_of(CHECKS)}
RETRACTED_FIELDS = {"key": _key, "issue": _issue, "date": _day, "reason": _one_of(REASONS)}
_MEANING = {
    "key": "is not an item key",
    "issue": "is not a whole number from 1",
    "date": "is not a day written YYYY-MM-DD",
    "kind": f"is not one of {', '.join(KINDS)}",
    "check": f"is not one of {', '.join(CHECKS)}",
    "reason": f"is not one of {', '.join(REASONS)}",
}


def _refuse(problem: str) -> CommunityError:
    return CommunityError(f"{RELATIVE_PATH}: {problem}")


def _old_form(document: dict[str, Any]) -> bool:
    """Whether a report of the file is of the old form: a link for its issue, or none of the fields the new form added."""
    reports = document.get("reports")
    return isinstance(reports, list) and any(
        isinstance(entry, dict) and (isinstance(entry.get("issue"), str) or not {"kind", "date", "check"} & set(entry)) for entry in reports
    )


def _entries(entries: Any, name: str, fields: dict[str, Any], refuse: Any, today: str | None) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise refuse(f"{name} must be a list")
    found = []
    for number, entry in enumerate(entries):
        where = f"{name}[{number}]"
        if not isinstance(entry, dict):
            raise refuse(f"{where} must be an object")
        missing = [field for field in fields if field not in entry]
        if missing:
            raise refuse(f"{where} has no {', '.join(missing)}")
        if set(entry) - set(fields):
            raise refuse(f"{where} has a field that is not allowed (the fields are {', '.join(fields)})")
        for field, valid in fields.items():
            if not valid(entry[field]):
                raise refuse(f"{where}: {field} {_MEANING[field]}")
        if today is not None and entry["date"] > today:
            raise refuse(f"{where}: date is a day after today ({today}, UTC)")
        found.append({field: entry[field] for field in fields})
    return found


def check_entries(
    reports: Any, retracted: Any, *, source: str = f"{RELATIVE_PATH}: ", today: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The two lists of entries read as the form allows, or a :class:`CommunityError` whose message starts with ``source``. The entries come back with their fields in the
    written order. Beyond the fields and the values of each entry:

    * an item and an issue appear once in all (in ``reports`` or in ``retracted``);
    * **an issue is in one list only**: a retraction moves every entry of the issue, and a retracted issue takes no new report, so a file with an issue in both lists is not one
      the command wrote;
    * with ``today`` (a day, UTC) no entry is dated after it.
    """

    def refuse(problem: str) -> CommunityError:
        return CommunityError(f"{source}{problem}")

    found_reports = _entries(reports, "reports", REPORT_FIELDS, refuse, today)
    found_retracted = _entries(retracted, "retracted", RETRACTED_FIELDS, refuse, today)
    pairs: set[tuple[str, int]] = set()
    for name, entries in (("reports", found_reports), ("retracted", found_retracted)):
        for number, entry in enumerate(entries):
            pair = (entry["key"], entry["issue"])
            if pair in pairs:
                raise refuse(f"{name}[{number}] repeats an item and an issue that the file has already")
            pairs.add(pair)
    if {entry["issue"] for entry in found_reports} & {entry["issue"] for entry in found_retracted}:
        raise refuse("an issue has entries in both reports and retracted (a retraction moves every entry of the issue, and a retracted issue takes no new report)")
    return found_reports, found_retracted


def check_document(document: Any, *, today: str | None = None) -> dict[str, Any]:
    """The document of ``rules/community-seen.json`` read as the form allows, or a :class:`CommunityError`. The entries come back with their fields in the written order.
    With ``today`` (a day, UTC) neither the version nor an entry may be dated after it."""
    if not isinstance(document, dict):
        raise _refuse("must hold an object")
    if _old_form(document):
        raise CommunityError(OLD_FORM)
    missing = [field for field in TOP_FIELDS if field not in document]
    if missing:
        raise _refuse(f"has no {', '.join(missing)}")
    if set(document) - set(TOP_FIELDS):
        raise _refuse(f"has a field that is not allowed (the fields are {', '.join(TOP_FIELDS)})")
    if not _day(document["version"]):
        raise _refuse("version must be a day written YYYY-MM-DD")
    if today is not None and document["version"] > today:
        raise _refuse(f"version is a day after today ({today}, UTC)")
    reports, retracted = check_entries(document["reports"], document["retracted"], today=today)
    return {"version": document["version"], "reports": reports, "retracted": retracted}


def read_document(path: str | os.PathLike[str], *, today: str | None = None) -> dict[str, Any]:
    """Read ``rules/community-seen.json`` (or a file of that form) strictly: strict JSON, then :func:`check_document` with ``today`` (the UTC day of the clock when none is
    given): a day after it is a typing mistake or a date made up. :class:`CommunityError` for anything else."""
    try:
        document = load_strict(path)
    except JsonFileError as error:
        raise CommunityError(str(error)) from error
    except OSError as error:
        raise CommunityError(f"cannot read {RELATIVE_PATH}") from error
    return check_document(document, today=today_utc() if today is None else today)


def _order(entry: dict[str, Any]) -> tuple[str, int]:
    return entry["key"], entry["issue"]


def sorted_entries(entries: Any) -> list[dict[str, Any]]:
    """The entries in the order the file keeps them: by key as text (as the catalog is sorted), then by issue."""
    return sorted(entries, key=_order)


def render_document(document: dict[str, Any]) -> str:
    """The text of the file for ``document``: the fields in the written order, the entries sorted (by key as text, then by issue), one to a line."""
    reports = sorted(({field: entry[field] for field in REPORT_FIELDS} for entry in document["reports"]), key=_order)
    retracted = sorted(({field: entry[field] for field in RETRACTED_FIELDS} for entry in document["retracted"]), key=_order)
    return render({"version": document["version"], "reports": reports, "retracted": retracted}, per_line=("reports", "retracted"))


# ---- the address of an issue ----------------------------------------------------------------------------------------------------------


def issue_url(owner: Any, number: Any) -> str:
    """The address of issue ``number`` of the project's repository, built from the account that owns it (the ``--owner`` of the build). The file never holds one.

    The owner is held to the form of a GitHub account name and is never the placeholder of the repository files; the number is a whole number from 1 (as in the file).
    """
    if not isinstance(owner, str) or _OWNER.fullmatch(owner) is None or owner.lower() == PLACEHOLDER_OWNER:
        raise CommunityError("the owner is not the name of a GitHub account (letters, digits and single hyphens; not the placeholder of the repository files)")
    if not _issue(number):
        raise CommunityError("the issue is not a whole number from 1")
    return f"https://github.com/{owner}/{REPOSITORY}/issues/{number}"


# ---- the commands ---------------------------------------------------------------------------------------------------------------------


def _slots_of(root: Path, key: str) -> list[str] | None:
    """The slots of the item ``key`` in the catalog under ``root`` (None: the catalog has no such item)."""
    try:
        document = load_strict(root / CATALOG_PATH)
    except FileNotFoundError as error:
        raise CommunityError(f"{CATALOG_PATH} is missing: build the catalog first") from error
    except (JsonFileError, OSError) as error:
        raise CommunityError(f"{CATALOG_PATH} cannot be read") from error
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, list):
        raise CommunityError(f"{CATALOG_PATH} is not a catalog")
    for item in items:
        if isinstance(item, dict) and item.get("key") == key:
            slots = item.get("slots")
            if not isinstance(slots, list) or not all(isinstance(slot, str) for slot in slots):
                raise CommunityError(f"{CATALOG_PATH} is not a catalog (an item has no list of slots)")
            return slots
    return None


def _read(root: Path, today: str) -> dict[str, Any] | None:
    path = root / RELATIVE_PATH
    return read_document(path, today=today) if path.exists() else None


def _write(root: Path, document: dict[str, Any]) -> None:
    """Replace the file whole or not at all (a temporary file beside it, then a rename), sorted."""
    name = Path(RELATIVE_PATH).name
    try:
        commit_files(root / Path(RELATIVE_PATH).parent, {name: render_document(document)}, last=name)
    except (OSError, ValueError) as error:
        raise CommunityError(f"cannot write {RELATIVE_PATH} ({type(error).__name__})") from error


def add_report(root: str | os.PathLike[str], *, key: str, issue: int, kind: str, today: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add the report ``key`` of ``issue`` to the file under ``root``: ``(the entry, the document written)``.

    :class:`CommunityError`, and nothing written, when the key is not a wearable of the catalog, when the file is damaged or of the old form, when the file has the item and
    the issue already, or when the issue was retracted: a retraction is final for the issue, whatever the item is, so a rejected issue cannot be filled again.
    """
    base = Path(root)
    today = today or today_utc()
    if not _key(key) or not _issue(issue) or kind not in KINDS:
        raise CommunityError("a report needs an item key, an issue number from 1 and a kind from the list")
    document = _read(base, today) or {"version": today, "reports": [], "retracted": []}
    slots = _slots_of(base, key)
    if slots is None:
        raise CommunityError(f"{key} is not an item of {CATALOG_PATH}")
    if not WEARABLE_SLOTS & set(slots):
        raise CommunityError(f"{key} is not a wearable of {CATALOG_PATH} (it lists no slot of a place of a kit)")
    if any(entry["key"] == key and entry["issue"] == issue for entry in document["reports"]):
        raise CommunityError(f"{key} is already reported in issue {issue}")
    if any(entry["issue"] == issue for entry in document["retracted"]):
        raise CommunityError(f"issue {issue} was retracted, and a retraction is final for the issue: a new report is a new issue")
    entry = {"key": key, "kind": kind, "issue": issue, "date": today, "check": CHECKS[0]}
    document = {"version": today, "reports": [*document["reports"], entry], "retracted": document["retracted"]}
    _write(base, document)
    return entry, document


def retract_issue(root: str | os.PathLike[str], *, issue: int, reason: str, today: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Move every report of ``issue`` to ``retracted`` with ``reason``: ``(the entries made, the document written)``.

    :class:`CommunityError`, and nothing written, when nobody reported the issue or when it is retracted already.
    """
    base = Path(root)
    today = today or today_utc()
    if not _issue(issue) or reason not in REASONS:
        raise CommunityError("a retraction needs an issue number from 1 and a reason from the list")
    document = _read(base, today)
    moved = [entry for entry in (document["reports"] if document else []) if entry["issue"] == issue]
    if document is None or not moved:
        if document is not None and any(entry["issue"] == issue for entry in document["retracted"]):
            raise CommunityError(f"issue {issue} is already retracted")
        raise CommunityError(f"no report of issue {issue}" + ("" if document is not None else f" ({RELATIVE_PATH} does not exist yet)"))
    made = sorted(({"key": entry["key"], "issue": issue, "date": today, "reason": reason} for entry in moved), key=_order)
    document = {
        "version": today,
        "reports": [entry for entry in document["reports"] if entry["issue"] != issue],
        "retracted": [*document["retracted"], *made],
    }
    _write(base, document)
    return made, document


# ---- the command line -----------------------------------------------------------------------------------------------------------------


class _Usage(Exception):
    """A command line that argparse refused; its message is the line to print."""


#: what each option says of a value it refuses (the words are ours: what was typed is not repeated)
KEY_MEANING = "is not an item key (such as w123)"
ISSUE_MEANING = "is not a whole number from 1"
KIND_MEANING = f"is not one of {', '.join(KINDS)}"
REASON_MEANING = f"is not one of {', '.join(REASONS)}"
#: the one line a command line argparse cannot account for gets (see :meth:`_Parser.error`)
FORM = "the command line is not one of: add --key wNNN --issue N --kind seen|tier --screenshot-checked, or retract --issue N --reason R (see --help)"
#: the only things argparse says that hold no text the maintainer typed: the options it requires (the names are the command's own), an option without its value, and a value
#: that one of the types above refused (with our words). Everything else it says quotes the input: an unrecognized argument, an invalid choice of a command, an explicit value
#: for a flag that takes none.
_OWN_NAME = r"(?:--[a-z-]+|\{[a-z,]+\})"
_SAFE = (
    re.compile(rf"the following arguments are required: {_OWN_NAME}(?:, {_OWN_NAME})*"),
    re.compile(r"argument --[a-z-]+: (?:expected one argument|" + "|".join(re.escape(text) for text in (KEY_MEANING, ISSUE_MEANING, KIND_MEANING, REASON_MEANING)) + ")"),
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        """One line, no usage text, and never a word the maintainer typed: argparse quotes the arguments it does not understand (``unrecognized arguments: --note reported
        by <name>``, ``invalid choice: '<name>'``), so only its own words about the command's options pass, and any other message becomes :data:`FORM`."""
        raise _Usage(message if any(safe.fullmatch(message) for safe in _SAFE) else FORM)


def _argument(valid: Any, meaning: str):
    """An argparse type that accepts the text when ``valid`` says so and otherwise refuses with ``meaning`` (what the maintainer typed is not repeated)."""

    def convert(text: str) -> str:
        if not valid(text):
            raise argparse.ArgumentTypeError(meaning)
        return text

    return convert


def _issue_number(text: str) -> int:
    return int(_argument(lambda value: _ISSUE_ARGUMENT.fullmatch(value) is not None, ISSUE_MEANING)(text))


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="python -m trioforge.community",
        description=f"Keep {RELATIVE_PATH}, the reports from players that a maintainer accepted: add one, or retract the reports of an issue.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="{add,retract}")
    add = commands.add_parser("add", help="record a report", allow_abbrev=False)
    add.add_argument("--key", required=True, type=_argument(_key, KEY_MEANING), help="the item: a wearable of derived/catalog.json, such as w123")
    add.add_argument("--issue", required=True, type=_issue_number, help="the number of the issue where it was reported")
    add.add_argument("--kind", required=True, type=_argument(lambda value: value in KINDS, KIND_MEANING), help=f"what it reports: {' or '.join(KINDS)}")
    add.add_argument("--screenshot-checked", action="store_true", help="required: a maintainer has checked a screenshot of the item window")
    retract = commands.add_parser("retract", help="move the reports of an issue to retracted", allow_abbrev=False)
    retract.add_argument("--issue", required=True, type=_issue_number, help="the number of the issue")
    retract.add_argument("--reason", required=True, type=_argument(lambda value: value in REASONS, REASON_MEANING), help=f"one of {', '.join(REASONS)}")
    return parser


def _entry_line(label: str, entry: dict[str, Any]) -> str:
    return f"{label} {json.dumps(entry, ensure_ascii=False, separators=(',', ':'))}"


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``add`` or ``retract``; 0 when it is done, 2 (one line on standard error, the file as it was) when it is refused or fails."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "add":
            if not args.screenshot_checked:
                raise CommunityError("--screenshot-checked is required: a report counts only after a maintainer has checked a screenshot of the item window")
            entry, document = add_report(REPO_ROOT, key=args.key, issue=args.issue, kind=args.kind, today=today_utc())
            lines = [_entry_line("added", entry)]
        else:
            made, document = retract_issue(REPO_ROOT, issue=args.issue, reason=args.reason, today=today_utc())
            lines = [_entry_line("retracted", entry) for entry in made]
    except (_Usage, CommunityError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    lines.append(f"reports {len(document['reports'])}, retracted {len(document['retracted'])}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
