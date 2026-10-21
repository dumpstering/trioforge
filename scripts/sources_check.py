"""The weekly check of the sources, run by the Task Scheduler of the maintainer's computer.

::

    python scripts/sources_check.py

It looks at three things and writes a report for a person to read:

* **The wiki's recent changes**, in the main namespace only, since the last run less ten minutes (the clocks differ and a change can reach the list late; what the overlap
  repeats is dropped by its id, which the record of the run holds), and eight days back when there is no earlier run. A window with more changes than a run reads (40 pages
  of 500) is read as far as that: the report says the list is partial and up to when, and the next run goes on exactly from there. Of the pages that changed it lists only those
  that are items of the catalog (``derived/catalog.json``), found by the id of their page, so that a rename hides no edit, as code, with the ids of their revisions, and
  the moves and the deletions of those pages, with the number and the time of the log entry; for the others it counts the changes and says nothing else.
  Nothing the wiki wrote reaches the report but a title that is in the catalog and numbers.
* **EQL Tools**: the SHA-256 of its gear JSON and of its quest JSON, against the last run's.
* **The patch notes page** of the wiki: whether its text changed since the last run, by its SHA-256.

At most one request a second, with the project's own user agent (it names the project and a page of its site that says who runs it, the about page unless ``--contact``
gives another), and robots.txt honoured for each host. An answer that is not a 200, or is not JSON where JSON is expected, is "unreachable" and never "changed": the record of such a
source is left as it was, and the next run asks again (for the wiki's changes, from the time the last run that read them stopped, or with none, from a first run's window; the report says which).

It writes ``sources-check-<UTC time>.md`` (a report is never replaced), its record for the next run, ``sources-check.state.json``, and, when the run itself has finished whatever it found, the stamp
``sources-check.last-run`` (a UTC time) that the release build reads, all in the folder of the checks: ``$TRIOFORGE_CHECKS_DIR`` if that is set (an absolute path, not in a git work tree), else
``~/.local/state/trioforge/checks``, on Windows too (``--out`` names another). That folder is outside
every worktree, so the release build, which runs from a worktree of its own, finds the stamp. It prints the counts and the place of the report. It never opens an issue:
the maintainer does that by hand, if the report calls for one.

``--dry-run FOLDER`` replays the answers recorded in the folder (see ``fixtures/checks/sources``) instead of asking the network, without waiting; it needs
``--out`` so that it cannot replace a real report. Exit status: 0 the run finished, 2 refused or failed (one line on standard error; ``TRIOFORGE_DEBUG`` adds the
traceback), 130 interrupted.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import traceback
import urllib.parse
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import checks_common as common

ROOT = Path(__file__).resolve().parents[1]
NAME = "sources-check"  # the name of the stamp, which the release build looks for
WIKI_API = "https://eqlwiki.com/api.php"
GEAR_URL = "https://eqltools.com/gear/data/gear-data.json"
QUESTS_URL = "https://eqltools.com/companion/data/quest-items.json"
EQLTOOLS_FILES = (("gear", GEAR_URL), ("quests", QUESTS_URL))
EQLTOOLS_HOLDS = {  # what each file holds, and in what shape: the gear file its items as an object keyed by the lookup key (or a list), the quest file a list of quests
    "gear": ("items", (dict, list), "the file has no items"),
    "quests": ("quests", (list,), "the file has no list of quests"),
}
EQLTOOLS_LICENCE = "CC BY-SA 4.0"  # what the files declare in meta.license, and what lets the project use them (as eqltools_quests.py holds them to)
PATCH_NOTES_TITLE = "Patch Notes"
SKIPPABLE = ("wiki", "eqltools", "patch-notes")  # the sources that --skip can leave out of a run
DAYS_BACK = 8  # the window of a first run
MAX_DAYS = 365
MAX_PAGES = 40  # pages of 500 changes: a window with more is read as far as this, and the list is partial
CHANGES_PER_PAGE = 500
RETENTION_DAYS = 90  # how long a wiki keeps its recent changes (the default of MediaWiki)
OVERLAP = datetime.timedelta(minutes=10)  # each window begins this long before the end of the last: the clocks differ, and a change can reach the list late
STATE_VERSION = 1
STATE_NAME = f"{NAME}.state.json"
NO_RECORD = (
    "there is no usable record of the previous run for some or all of what it held (its state file is damaged, or names a time that has not come); "
    "what could not be used is recorded again, and the wiki's changes are read from the window of a first run unless the time of the previous run could be used"
)
_API = {"format": "json", "formatversion": 2, "maxlag": 5}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_STAMPED = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_SEEN_ID = re.compile(r"[rl][1-9][0-9]{0,15}")  # r + a revision id, or l + the number of a log entry: a change that an earlier window held


Refused = common.Refused  # (the run cannot be made or cannot be written: one line on standard error, status 2, no stamp)


# ---- the catalog ---------------------------------------------------------------------------------------------------------------------------------------


class CatalogItem(NamedTuple):
    key: str
    revid: int | None  # the revision of the wiki page that the catalog was built from
    pageid: int | None = None  # the id of the wiki page, which a move or a rename does not change


def read_catalog(path: Path) -> dict[str, CatalogItem]:
    """The wiki titles of the items of the catalog (``derived/catalog.json``): ``{title: CatalogItem}``. An item with no wiki page is not a title to watch."""
    name = Path(path).name
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise Refused(f"cannot read the catalog {name}: {error.strerror or type(error).__name__}") from None
    except ValueError:
        raise Refused(f"the catalog {name} is not JSON") from None
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise Refused(f"the catalog {name} has no list of items")
    titles: dict[str, CatalogItem] = {}
    for item in items:
        wiki = item.get("wiki")
        title = wiki.get("title") if isinstance(wiki, dict) else None
        key = item.get("key")
        if isinstance(title, str) and title and isinstance(key, str):
            revid, pageid = wiki.get("revid"), wiki.get("pageid")
            titles.setdefault(title, CatalogItem(key, revid if _positive(revid) else None, pageid if _positive(pageid) else None))
    if not titles:
        raise Refused(f"the catalog {name} lists no item with a wiki page")
    return titles


# ---- the record of the previous run ---------------------------------------------------------------------------------------------------------------------


@dataclass
class State:
    checked_until: datetime.datetime | None = None  # the wiki's changes were read up to this time
    partial: bool = False  # ... and the list stopped there because the window held more than a run reads: the next window begins exactly there
    seen: list[str] = field(default_factory=list)  # the changes of the last OVERLAP before that time (_SEEN_ID), which the next window holds again
    files: dict[str, dict[str, Any]] = field(default_factory=dict)  # the EQL Tools files: {"sha256", "bytes"}
    patch_notes: dict[str, Any] | None = None  # {"sha256", "revid"}
    damaged: bool = False


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _file_record(value: Any) -> dict[str, Any] | None:
    """The record of an EQL Tools file, ``{"sha256", "bytes"}``, if ``value`` is one."""
    if isinstance(value, dict) and isinstance(value.get("sha256"), str) and _SHA256.fullmatch(value["sha256"]) and _is_count(value.get("bytes")):
        return {"sha256": value["sha256"], "bytes": value["bytes"]}
    return None


def _patch_record(value: Any) -> dict[str, Any] | None:
    """The record of the patch notes, ``{"sha256", "revid"}`` (the revision may be missing), if ``value`` is one."""
    if isinstance(value, dict) and isinstance(value.get("sha256"), str) and _SHA256.fullmatch(value["sha256"]):
        return {"sha256": value["sha256"], **({"revid": value["revid"]} if _is_count(value.get("revid")) else {})}
    return None


def read_state(path: Path) -> State:
    """The record of the previous run. A file that is not there is a first run; one that cannot be read is a first run too, and the report says so. A piece of it that
    is damaged is left out and the rest is kept."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return State()
    except OSError:
        return State(damaged=True)
    try:
        document = json.loads(raw)
    except ValueError:
        return State(damaged=True)
    if not isinstance(document, dict):
        return State(damaged=True)
    state = State()
    changes = document.get("recent_changes")
    if changes is not None:
        try:
            state.checked_until = common.parse_utc(changes.get("checked_until") if isinstance(changes, dict) else None)
        except ValueError:
            state.damaged = True
        if isinstance(changes, dict) and "partial" in changes:
            if isinstance(changes["partial"], bool):
                state.partial = changes["partial"]
            else:
                state.damaged = True
        if isinstance(changes, dict) and "seen" in changes:
            seen = changes["seen"]
            if isinstance(seen, list) and all(isinstance(item, str) and _SEEN_ID.fullmatch(item) for item in seen):
                state.seen = list(seen)
            else:
                state.damaged = True
    tools = document.get("eqltools")
    if tools is not None and not isinstance(tools, dict):
        state.damaged = True
    for name, _ in EQLTOOLS_FILES:
        if isinstance(tools, dict) and name in tools:
            record = _file_record(tools[name])
            if record is None:
                state.damaged = True
            else:
                state.files[name] = record
    if "patch_notes" in document:
        state.patch_notes = _patch_record(document["patch_notes"])
        state.damaged = state.damaged or state.patch_notes is None
    return state


# ---- what a run finds ----------------------------------------------------------------------------------------------------------------------------------


@dataclass
class Edited:
    """A page of the catalog that changed on the wiki in the window."""

    title: str  # the title of the catalog, whatever the page is called on the wiki now
    key: str
    revisions: list[int]
    last: str | None
    catalog_revid: int | None
    events: list[tuple[str, int, str]] = field(default_factory=list)  # ("moved" or "deleted", the number of the log entry, its time), oldest first


@dataclass
class WikiChanges:
    total: int  # the changes to pages of the main namespace that the previous window did not hold (each revision once)
    pages: list[Edited]
    ids: dict[str, str] = field(default_factory=dict)  # every change of the window by its id (_SEEN_ID) and its time, for the next window to drop
    partial_until: datetime.datetime | None = None  # the list is partial: the window held more changes than a run reads, and this is the time of the last one read


@dataclass
class Observation:
    """What one hashed source gave: a status of ``recorded`` (the first time), ``unchanged``, ``changed``, ``unreachable`` or ``skipped`` (left out with ``--skip``)."""

    status: str
    sha256: str | None = None
    size: int | None = None
    revid: int | None = None
    previous: dict[str, Any] | None = None  # the record of the previous run
    reason: str | None = None  # why it is unreachable, or what left it out


@dataclass
class Findings:
    started: datetime.datetime
    since: datetime.datetime
    why: str  # where the window starts from, in words
    carried_until: datetime.datetime | None  # the time the previous run read up to, if it can be believed
    notes: list[str]
    wiki: WikiChanges | str | None  # a str is the reason the changes could not be read; None, that they were left out (--skip wiki)
    files: dict[str, Observation]
    patch_notes: Observation
    days: int = DAYS_BACK  # how far back a first run (and so a run with no time to go on from) reads
    carried_partial: bool = False  # the time carried is where a partial list stopped


def _api_url(params: Mapping[str, Any]) -> str:
    return WIKI_API + "?" + urllib.parse.urlencode({**params, **_API})


def _wiki_answer(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise common.Unreachable("the answer is not a JSON object")
    if "error" in data or "errors" in data:
        raise common.Unreachable("the wiki answered with an error")
    return data


def _positive(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _catalog_title(change: Mapping[str, Any], by_page: Mapping[int, str], titles: Mapping[str, CatalogItem], log: bool) -> str | None:
    """The catalog title of the page that a change is to, or None. The id of the page decides: a page that was renamed or moved is the same page under its new title, and another
    page that now has the old title is not it. A change with no usable id is matched by its title, and so is a log entry -- the id of a deleted page is gone and that of a moved page
    may be the redirect's -- and so is a page of a catalog that has no id for it."""
    pageid, title = change.get("pageid"), change.get("title")
    if _positive(pageid) and pageid in by_page:
        return by_page[pageid]
    if not isinstance(title, str) or title not in titles:
        return None
    if log or titles[title].pageid is None or not _positive(pageid):
        return title
    return None


def _log_event(change: Mapping[str, Any]) -> tuple[str, int, str] | None:
    """The move or the deletion that a log entry of the changes records, as ``(kind, number, time)``; None for any other entry, or one that has no number or time to say."""
    logtype, action = change.get("logtype"), change.get("logaction")
    if logtype == "move":
        kind = "moved"
    elif logtype == "delete" and action in ("delete", "delete_redir"):
        kind = "deleted"
    else:
        return None
    number = change.get("logid") if _positive(change.get("logid")) else change.get("rcid")
    stamp = change.get("timestamp")
    if not _positive(number) or not isinstance(stamp, str) or not _STAMPED.fullmatch(stamp):
        return None
    return kind, number, stamp


def fetch_changes(
    fetcher: common.Fetcher, titles: Mapping[str, CatalogItem], since: datetime.datetime, until: datetime.datetime, seen: Collection[str] = ()
) -> WikiChanges:
    """The main-namespace changes of the wiki between two times: how many edits and new pages there were, and which pages of the catalog they were to or were moved or deleted.

    Edits, new pages and log entries (``rctype``; of the log, only moves and deletions are looked at), the main namespace only (asked for with ``rcnamespace``, and each change is
    checked for it again), and no free text is asked for. A change is matched to the catalog by the id of its page (:func:`_catalog_title`). Raises :class:`common.Unreachable` if any
    page of the changes cannot be read, so that half a list is never shown. A change whose id is in ``seen`` was held by the window before (they overlap) and is dropped.
    """
    already = set(seen)
    ids: dict[str, str] = {}
    by_page = {item.pageid: title for title, item in titles.items() if item.pageid is not None}
    base = {
        "action": "query",
        "list": "recentchanges",
        "rcnamespace": 0,
        "rctype": "edit|new|log",
        "rcprop": "title|ids|timestamp|loginfo",
        "rclimit": CHANGES_PER_PAGE,
        "rcdir": "newer",
        "rcstart": common.utc_text(since),
        "rcend": common.utc_text(until),
    }
    params: dict[str, Any] = dict(base)
    tokens: set[tuple[tuple[str, str], ...]] = set()  # the continuations that were followed
    counted: set[int] = set()
    newest = ""  # the time of the latest change read, whatever it was to
    revisions: dict[str, set[int]] = {}
    last: dict[str, str] = {}
    events: dict[str, set[tuple[str, int, str]]] = {}
    partial: datetime.datetime | None = None
    for _ in range(MAX_PAGES):
        data = _wiki_answer(fetcher.get_json(_api_url(params)))
        query = data.get("query")
        changes = query.get("recentchanges") if isinstance(query, dict) else None
        if not isinstance(changes, list) or not all(isinstance(change, dict) for change in changes):
            raise common.Unreachable("the answer is not a list of changes")
        for change in changes:
            stamp = change.get("timestamp")
            valid = isinstance(stamp, str) and _STAMPED.fullmatch(stamp) is not None
            if valid and stamp > newest:
                newest = stamp  # (the list is in order of time: this is how far it has been read, whatever the change was to)
            title, revid, namespace, kind = change.get("title"), change.get("revid"), change.get("ns"), change.get("type")
            if type(namespace) is not int or namespace != 0 or kind not in ("edit", "new", "log"):
                continue  # (not the main namespace, or a change of a kind that is not looked at)
            when = stamp if valid else common.utc_text(until)  # (a change with no time is remembered as if it were the latest)
            if kind == "log":
                event = _log_event(change)
                found = _catalog_title(change, by_page, titles, log=True) if event is not None else None
                if event is not None and found is not None and f"l{event[1]}" not in already:
                    events.setdefault(found, set()).add(event)
                    ids[f"l{event[1]}"] = when
                continue
            if not isinstance(title, str) or not _positive(revid) or f"r{revid}" in already:
                continue
            counted.add(revid)
            ids[f"r{revid}"] = when
            found = _catalog_title(change, by_page, titles, log=False)
            if found is not None:
                revisions.setdefault(found, set()).add(revid)
                stamp = change.get("timestamp")
                if isinstance(stamp, str) and _STAMPED.fullmatch(stamp) and stamp > last.get(found, ""):
                    last[found] = stamp
        following = data.get("continue")
        if not following:
            break
        if not isinstance(following, dict):
            raise common.Unreachable("the wiki gave a continuation that cannot be followed")
        token = tuple(sorted((str(name), str(value)) for name, value in following.items()))
        if token in tokens:
            raise common.Unreachable("the wiki repeated a continuation token")
        tokens.add(token)
        params = {**base, **following}
    else:
        if not newest:
            raise common.Unreachable(f"more than {MAX_PAGES} pages of changes")  # (no change at all to say where the window can move to: it would be stuck)
        partial = common.parse_utc(newest)
    pages = [
        Edited(title, titles[title].key, sorted(revisions.get(title, ())), last.get(title), titles[title].revid, sorted(events.get(title, ()), key=lambda event: (event[2], event[1])))
        for title in sorted({*revisions, *events})
    ]
    pages.sort(key=lambda page: (page.title.casefold(), page.title))
    return WikiChanges(len(counted), pages, ids, partial)


def _compare(previous: dict[str, Any] | None, sha256: str) -> str:
    return "recorded" if previous is None else "unchanged" if previous["sha256"] == sha256 else "changed"


def _check_shape(document: dict[str, Any], name: str | None) -> None:
    """Raise :class:`common.Unreachable` if ``document`` is not the file ``name`` of EQL Tools: it must declare the licence in ``meta.license`` and hold what it holds, in the shape the
    readers of the project take it in (``read_eqltools``: ``items`` is an object or a list; ``read_quests``: ``quests`` is a list). (A JSON
    object that is something else, such as a notice from the host, is not a change of the file, and a file that stops declaring the licence is not one the project may use.)"""
    meta = document.get("meta")
    if not isinstance(meta, dict) or meta.get("license") != EQLTOOLS_LICENCE:
        raise common.Unreachable(f"the file does not declare the licence {EQLTOOLS_LICENCE}")
    holds = EQLTOOLS_HOLDS.get(name or "")
    if holds is not None and not isinstance(document.get(holds[0]), holds[1]):
        raise common.Unreachable(holds[2])


def observe_file(fetcher: common.Fetcher, url: str, previous: dict[str, Any] | None, name: str | None = None) -> Observation:
    """A JSON file of EQL Tools: the SHA-256 of its bytes (unpacked), against the record of the previous run. With its ``name`` (gear or quests) it is held to its own shape."""
    try:
        body = fetcher.get(url).body
        document = common.decode_json(body)
        if not isinstance(document, dict):
            raise common.Unreachable("the answer is not a JSON object")
        if name is not None:
            _check_shape(document, name)
    except common.Unreachable as error:
        return Observation("unreachable", previous=previous, reason=error.reason)
    digest = hashlib.sha256(body).hexdigest()
    return Observation(_compare(previous, digest), digest, len(body), previous=previous)


def observe_patch_notes(fetcher: common.Fetcher, previous: dict[str, Any] | None) -> Observation:
    """The patch notes page of the wiki: the SHA-256 of its text, against the record of the previous run."""
    params = {"action": "query", "prop": "revisions", "titles": PATCH_NOTES_TITLE, "rvprop": "ids|timestamp|content", "rvslots": "main"}
    try:
        data = _wiki_answer(fetcher.get_json(_api_url(params)))
        query = data.get("query")
        pages = query.get("pages") if isinstance(query, dict) else None
        page = pages[0] if isinstance(pages, list) and pages and isinstance(pages[0], dict) else None
        if page is None:
            raise common.Unreachable("no text in the answer")
        if page.get("missing"):
            raise common.Unreachable("the page is not on the wiki")
        if page.get("title") != PATCH_NOTES_TITLE:
            raise common.Unreachable("the answer is about another page")
        revisions = page.get("revisions")
        revision = revisions[0] if isinstance(revisions, list) and revisions and isinstance(revisions[0], dict) else {}
        slots = revision.get("slots")
        main = slots.get("main") if isinstance(slots, dict) else None
        content = main.get("content") if isinstance(main, dict) else None
        if not isinstance(content, str):
            raise common.Unreachable("no text in the answer")
    except common.Unreachable as error:
        return Observation("unreachable", previous=previous, reason=error.reason)
    revid = revision.get("revid")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return Observation(_compare(previous, digest), digest, revid=revid if _positive(revid) else None, previous=previous)


def window(state: State, started: datetime.datetime, days: int) -> tuple[datetime.datetime, str, datetime.datetime | None, list[str]]:
    """Where the wiki's changes are read from, in words, the time of the previous run if it can be believed, and what the report should say about the window."""
    notes = []
    carried = state.checked_until
    if carried is not None and carried > started:
        carried = None  # (a run that looked up to a time that has not come: a clock that was wrong)
    if state.damaged or carried is None and state.checked_until is not None:
        notes.append(NO_RECORD)
    if carried is not None and state.partial:
        since, why = carried, "the previous run, which stopped early because its list was partial"  # (that time is the wiki's own, so there is no clock to allow for)
    elif carried is not None:
        since = carried - OVERLAP
        why = f"the previous run, less {OVERLAP.seconds // 60} minutes, because the clocks differ and a change can reach the list late"
    else:
        since, why = started - datetime.timedelta(days=days), f"{days} day{'s' if days != 1 else ''} back; there is no earlier run"
    if started - since > datetime.timedelta(days=RETENTION_DAYS):
        cutoff = common.utc_text(started - datetime.timedelta(days=RETENTION_DAYS))
        notes.append(f"The wiki keeps its recent changes for about {RETENTION_DAYS} days, so the changes from before {cutoff} are not in the list.")
    return since, why, carried, notes


def _skipped(previous: dict[str, Any] | None, source: str) -> Observation:
    return Observation("skipped", previous=previous, reason=f"--skip {source}")


def check(
    fetcher: common.Fetcher,
    titles: Mapping[str, CatalogItem],
    state: State,
    started: datetime.datetime,
    days: int,
    skip: Collection[str] = (),
) -> Findings:
    """One run: the wiki's changes, then the patch notes, then the two files of EQL Tools; the sources named in ``skip`` (of :data:`SKIPPABLE`) are not asked for."""
    since, why, carried, notes = window(state, started, days)
    wiki: WikiChanges | str | None
    if "wiki" in skip:
        wiki = None
    else:
        try:
            wiki = fetch_changes(fetcher, titles, since, started, state.seen)
        except common.Unreachable as error:
            wiki = error.reason
    patch_notes = _skipped(state.patch_notes, "patch-notes") if "patch-notes" in skip else observe_patch_notes(fetcher, state.patch_notes)
    files = {
        name: _skipped(state.files.get(name), "eqltools") if "eqltools" in skip else observe_file(fetcher, url, state.files.get(name), name) for name, url in EQLTOOLS_FILES
    }
    return Findings(started, since, why, carried, notes, wiki, files, patch_notes, days, state.partial and carried is not None)


# ---- the summary, the report and the next state ------------------------------------------------------------------------------------------------------------


def _next_window(findings: Findings) -> str:
    """What the next run will do about the wiki's changes if this one could not read them (or left them out), in words: the record is kept as it was, so it goes on from the time
    carried -- or, with none to go on from, reads the window of a first run."""
    if findings.carried_until is None:
        return f"there is no earlier time to go on from, so the next run reads {findings.days} {_plural(findings.days, 'day', 'days')} back, as a first run does"
    when = common.utc_text(findings.carried_until)
    if findings.carried_partial:
        return f"the next run goes on from where the last one that read them stopped, {when}"
    return f"the next run asks again from the time of the last run that read them, {when}, less {OVERLAP.seconds // 60} minutes"


def _day(when: datetime.datetime) -> str:
    return when.astimezone(datetime.timezone.utc).date().isoformat()


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def summary(findings: Findings) -> str:
    """The counts of the run, in one line (the words that the command prints after its name)."""
    wiki = findings.wiki
    if wiki is None:
        said = "wiki changes skipped"
    elif isinstance(wiki, str):
        said = "wiki changes unreachable"
    elif not wiki.pages:
        said = "no catalog title changed"
    else:
        said = f"{len(wiki.pages)} catalog {_plural(len(wiki.pages), 'title', 'titles')} changed"
    if isinstance(wiki, WikiChanges) and wiki.partial_until is not None:
        said += " (partial list)"
    files = ", ".join(f"{name} {found.status}" for name, found in findings.files.items())
    unreachable = int(isinstance(wiki, str)) + sum(found.status == "unreachable" for found in [*findings.files.values(), findings.patch_notes])
    return f"{said}; EQL Tools: {files}; patch notes {findings.patch_notes.status}; {unreachable} unreachable"


def _unreachable_line(label: str, found: Observation) -> str:
    kept = f"the record of the last run (sha256 `{found.previous['sha256']}`) stays" if found.previous else "there is no record of an earlier run"
    return f"- {label}: {found.status} ({found.reason}); {kept}"  # (unreachable, or skipped: the record is as it was either way)


def _file_line(label: str, found: Observation) -> str:
    if found.status in ("unreachable", "skipped"):
        return _unreachable_line(label, found)
    if found.status == "recorded":
        return f"- {label}: recorded (sha256 `{found.sha256}`, {found.size} bytes)"
    if found.status == "unchanged":
        return f"- {label}: unchanged (sha256 `{found.sha256}`)"
    return f"- {label}: changed (sha256 `{found.sha256}`, it was `{found.previous['sha256'] if found.previous else ''}`; {found.size} bytes)"


def _patch_line(found: Observation) -> str:
    if found.status in ("unreachable", "skipped"):
        return _unreachable_line("patch notes", found)
    revision = f"revision {found.revid}" if found.revid is not None else "no revision number"
    if found.status == "recorded":
        return f"- patch notes: recorded ({revision}, sha256 `{found.sha256}`)"
    if found.status == "unchanged":
        return f"- patch notes: unchanged ({revision}, sha256 `{found.sha256}`)"
    was = found.previous.get("revid") if found.previous else None
    return f"- patch notes: changed ({revision}{f', it was {was}' if was is not None else ''}; sha256 `{found.sha256}`, it was `{found.previous['sha256'] if found.previous else ''}`)"


def _edited_line(page: Edited) -> str:
    pieces = []
    if page.events:
        pieces.append(", ".join(f"{kind} on the wiki (log entry {number}, {when})" for kind, number, when in page.events))
    details = []
    if page.last:
        details.append(f"last edit {page.last}")
    if page.catalog_revid is not None:
        details.append(f"the catalog was built from {page.catalog_revid}")
    if page.revisions:
        ids = ", ".join(str(revid) for revid in page.revisions)
        pieces.append(f"{_plural(len(page.revisions), 'revision', 'revisions')} {ids}" + (f" ({'; '.join(details)})" if details else ""))
    elif details:
        pieces.append("; ".join(details))
    return f"- {common.code_span(page.title)}: " + "; ".join(pieces)


def render_report(findings: Findings) -> str:
    """The report, in Markdown. It holds the titles of the catalog that changed, numbers, hashes and the kinds of failure, and no other text from any site."""
    lines = [
        f"# Sources check, {_day(findings.started)}",
        "",
        f"Summary: {summary(findings)}.",
        "",
        f"Run at {common.utc_text(findings.started)}. This report is for you to read: nothing has been reported anywhere. If something in it needs an issue, open an issue by hand (docs/runbook-weekly.md says when and how).",
        "",
        f"## Wiki changes since {common.utc_text(findings.since)} ({findings.why})" if findings.wiki is not None else "## Wiki changes (left out)",
        "",
    ]
    for note in findings.notes:
        lines += [f"Note: {note}", ""]
    wiki = findings.wiki
    if wiki is None:
        lines.append(
            "- wiki changes: skipped (--skip wiki); the next run reads from the time of the last run that read them"
            + (
                f" ({common.utc_text(findings.carried_until)}), "
                + ("with no overlap, since that list was partial" if findings.carried_partial else f"less {OVERLAP.seconds // 60} minutes")
                if findings.carried_until is not None
                else f", and as there is none it reads {findings.days} {_plural(findings.days, 'day', 'days')} back, as a first run does"
            )
        )
    elif isinstance(wiki, str):
        lines.append(f"- wiki changes: unreachable ({wiki}); nothing is known of the changes in this window, and {_next_window(findings)}")
    else:
        if wiki.partial_until is not None:
            lines += [
                f"Note: the list is partial: this window holds more changes than a run reads ({MAX_PAGES} pages of {CHANGES_PER_PAGE}), so this run read them up to {common.utc_text(wiki.partial_until)} "
                "and the next run goes on from there.",
                "",
            ]
        total = f"{wiki.total} {_plural(wiki.total, 'change', 'changes')} in the main namespace"
        if not wiki.pages:
            lines.append(f"{total}; none of the changed pages is in the catalog.")
        else:
            count = len(wiki.pages)
            lines += [f"{total}; {count} of the changed pages {_plural(count, 'is', 'are')} in the catalog:", ""]
            lines += [_edited_line(page) for page in wiki.pages]
    lines += ["", "## EQL Tools", ""]
    lines += [_file_line(name, found) for name, found in findings.files.items()]
    lines += ["", "## Patch notes", "", _patch_line(findings.patch_notes), ""]
    return "\n".join(lines)


def next_state(old: State, findings: Findings) -> dict[str, Any]:
    """The record for the next run: what was read now, and, for a source that could not be read, the record it had."""
    document: dict[str, Any] = {"version": STATE_VERSION}
    if findings.wiki is None or isinstance(findings.wiki, str):
        if findings.carried_until is not None:
            document["recent_changes"] = {  # (the record as it was: the flag that the next window begins exactly there goes with the time, or the next run would start ten minutes early)
                "checked_until": common.utc_text(findings.carried_until),
                **({"partial": True} if findings.carried_partial else {}),
                **({"seen": old.seen} if old.seen else {}),
            }
    else:
        partial = findings.wiki.partial_until
        until = partial if partial is not None else findings.started
        floor = common.utc_text(until if partial is not None else until - OVERLAP)  # (only what the next window can hold again is remembered)
        seen = sorted(change for change, when in findings.wiki.ids.items() if when >= floor)
        document["recent_changes"] = {"checked_until": common.utc_text(until), **({"partial": True} if partial is not None else {}), **({"seen": seen} if seen else {})}
    tools = {}
    for name, found in findings.files.items():
        if found.status not in ("unreachable", "skipped"):
            tools[name] = {"sha256": found.sha256, "bytes": found.size}
        elif name in old.files:
            tools[name] = old.files[name]
    if tools:
        document["eqltools"] = tools
    patch = findings.patch_notes
    if patch.status not in ("unreachable", "skipped"):
        document["patch_notes"] = {"sha256": patch.sha256, **({"revid": patch.revid} if patch.revid is not None else {})}
    elif old.patch_notes is not None:
        document["patch_notes"] = old.patch_notes
    return document


# ---- the command ---------------------------------------------------------------------------------------------------------------------------------------


def _days(text: str) -> int:
    try:
        days = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number of days") from None
    if not 1 <= days <= MAX_DAYS:
        raise argparse.ArgumentTypeError(f"must be from 1 to {MAX_DAYS}")
    return days


def _parser() -> argparse.ArgumentParser:
    parser = common.Parser(
        prog="sources_check.py",
        description="The weekly check of the sources: the wiki's recent changes to items of the catalog, the files of EQL Tools and the patch notes. Writes a report and never opens an issue.",
    )
    parser.add_argument("--contact", default=common.DEFAULT_CONTACT, help=f"the page of the site that the user agent points to, which says who runs the check (default: {common.DEFAULT_CONTACT})")
    parser.add_argument("--catalog", type=common.path_argument, default=ROOT / "derived" / "catalog.json", help="the catalog whose titles are watched (default: derived/catalog.json)")
    parser.add_argument("--out", type=common.path_argument, help="the folder of the report, the record and the stamp (default: the folder of the checks, outside every worktree: $TRIOFORGE_CHECKS_DIR, else ~/.local/state/trioforge/checks)")
    parser.add_argument("--days", type=_days, default=DAYS_BACK, help=f"how far back the wiki's changes are read on a first run (default: {DAYS_BACK})")
    parser.add_argument(
        "--skip",
        action="append",
        choices=SKIPPABLE,
        default=[],
        metavar="SOURCE",
        help="leave a source out of the run, one of " + ", ".join(SKIPPABLE) + " (wiki: the recent changes; eqltools: its two files; patch-notes: the page), for a site that refuses the check; "
        "may be given more than once; the record of a source that is left out stays as it was",
    )
    parser.add_argument("--dry-run", type=common.path_argument, metavar="FOLDER", help="replay the answers recorded in FOLDER instead of asking the network (needs --out)")
    return parser


def _user_agent(args: argparse.Namespace) -> str:
    try:
        return common.user_agent(args.contact)
    except ValueError as error:
        raise Refused(f"--contact: {error}") from None


def _default_folder() -> Path:
    try:
        return common.default_folder()
    except ValueError as error:
        raise Refused(str(error)) from None


def _show(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _write_report(out: Path, started: datetime.datetime, text: str) -> Path:
    try:
        return common.write_new_report(out, NAME, started, text)
    except OSError as error:
        raise Refused(f"cannot write the report: {error.strerror or type(error).__name__}") from None


def _write(path: Path, text: str) -> None:
    try:
        common.write_text_atomic(path, text)
    except OSError as error:
        raise Refused(f"cannot write {path.name}: {error.strerror or type(error).__name__}") from None


def run_command(
    args: argparse.Namespace,
    *,
    transport: common.Transport | None,
    clock: Callable[[], float] | None,
    sleep: Callable[[float], None] | None,
    now: Callable[[], datetime.datetime],
) -> str:
    """The run: the report, the record and the stamp are written, and the counts and the place of the report are printed. Returns the text of the line of the log."""
    if args.dry_run is not None and args.out is None:
        raise Refused("a dry run needs --out FOLDER, so that it cannot replace a real report")
    if args.dry_run is not None and common.is_the_real_folder(args.out):
        raise Refused("a dry run cannot write into the folder of the real checks, which would replace a real report and a real stamp; give --out another folder")
    skip = set(args.skip)
    if skip >= set(SKIPPABLE):
        raise Refused("--skip cannot leave out every source: a run that asks for nothing would still leave a stamp that says the sources were checked")
    out = args.out if args.out is not None else _default_folder()
    agent = _user_agent(args)
    titles = read_catalog(args.catalog)
    if args.dry_run is not None:
        try:
            transport = common.ReplayTransport.from_directory(args.dry_run)
        except ValueError as error:
            raise Refused(str(error)) from None
        virtual = common.VirtualTime()
        clock, sleep = virtual.clock, virtual.sleep
    elif transport is None:
        transport = common.real_transport()
    fetcher = common.Fetcher(agent, transport=transport, clock=clock, sleep=sleep)
    old = read_state(out / STATE_NAME)
    started = now()
    findings = check(fetcher, titles, old, started, args.days, skip)
    report = _write_report(out, started, render_report(findings))
    _write(out / STATE_NAME, json.dumps(next_state(old, findings), indent=1, sort_keys=True) + "\n")
    try:
        common.write_stamp(out, NAME, now())  # (last: a run that did not get here leaves no stamp)
    except OSError as error:
        raise Refused(f"cannot write the stamp: {error.strerror or type(error).__name__}") from None
    print(f"{NAME}: {summary(findings)}")
    print(f"report: {_show(report)}")
    return f"{summary(findings)}; report {report.name}"


def main(
    argv: list[str] | None = None,
    *,
    transport: common.Transport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], datetime.datetime] | None = None,
) -> int:
    """The command. ``transport``, ``clock``, ``sleep`` and ``now`` are for the tests, which replace the network and the wall clock."""
    when = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
    return common.run_main(
        NAME,
        _parser(),
        argv,
        lambda args: run_command(args, transport=transport, clock=clock, sleep=sleep, now=when),
        now=when,
    )


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):  # (a console in an old code page loses a character of a line, not the lines after it)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    sys.exit(main())
