"""The monthly check of the pins, run by the Task Scheduler of the maintainer's computer.

::

    python scripts/pins_check.py

It reads what the repository pins and asks for newer versions:

* **The actions** of ``.github/workflows`` that are pinned to a commit: the highest final release of each (not the one made last), with the commit of its tag, against the pinned commit (and the
  pinned tag, which is in the comment after the commit). A tag that now points at another commit than the pin is reported as moved.
* **The Python packages** of ``requirements.txt`` and **the npm packages** of ``package.json`` that are pinned to an exact version, against the releases of
  PyPI and the versions of npm.
* **Node and Python**: the series that the workflows name (``24``, ``3.12``) against the releases of Node and of Python on GitHub, and the version this computer has.

**A newer version counts only when it is at least 14 days old**, by its release date on PyPI, npm or GitHub. A younger one is named, apart, with the day it counts
from. Pre-releases, yanked and deprecated versions are left out. The answer for each pin is one of: newer, newer but too young, current, moved (a tag), unreachable,
or not checked (a pin that is not exact, an action that is not pinned to a commit, a repository with no release).

The requests are unauthenticated GETs of the documented APIs of api.github.com, pypi.org and registry.npmjs.org (so robots.txt, which is for crawlers, is not read),
at most one a second, with the project's own user agent. An answer that is not a 200, or is not JSON where JSON is expected, is "unreachable" and never "newer".

It never changes a pin or any file of the repository. It writes ``pins-check-<UTC time>.md`` (a report is never replaced) and, when the run has finished whatever it found, the stamp
``pins-check.last-run`` (a UTC time), in the folder of the checks: ``$TRIOFORGE_CHECKS_DIR`` if that is set (an absolute path, not in a git work tree), else
``~/.local/state/trioforge/checks``, on Windows too (``--out`` names another). It prints the counts and the place of the report, and it never
opens an issue.

``--dry-run FOLDER`` replays the answers recorded in the folder (see ``fixtures/checks/pins``) instead of asking the network, without waiting; it needs ``--out`` so
that it cannot replace a real report. Exit status: 0 the run finished, 2 refused or failed (one line on standard error; ``TRIOFORGE_DEBUG`` adds the traceback),
130 interrupted.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import traceback
import urllib.parse
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import checks_common as common

ROOT = Path(__file__).resolve().parents[1]
NAME = "pins-check"  # the name of the stamp
MIN_AGE_DAYS = 14
GITHUB = "https://api.github.com"
RELEASES = GITHUB + "/repos/{repo}/releases?per_page=100"  # the list, from which the highest final release is taken: /releases/latest is the one made last, not the highest
COMMIT_OF_TAG = GITHUB + "/repos/{repo}/commits/{tag}"
PYPI_PACKAGE = "https://pypi.org/pypi/{name}/json"
NPM_PACKAGE = "https://registry.npmjs.org/{name}"
RUNTIMES = (  # the releases of each runtime that the workflows can name a series of
    ("node", GITHUB + "/repos/nodejs/node/releases?per_page=100"),
    ("python", GITHUB + "/repos/actions/python-versions/releases?per_page=100"),
)
NODE_TIMEOUT = 15
_USES = re.compile(r"""^\s*(?:-\s+)?uses:\s*(?P<ref>"[^"]*"|'[^']*'|[^\s#]+)\s*(?:#\s*(?P<comment>.*?))?\s*$""")
_PINNED = re.compile(r"(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/(?P<path>[^@\s]+))?@(?P<sha>[0-9a-f]{40})")
_TAG = re.compile(r"v?[0-9]+(?:\.[0-9]+)*")
_LOOKS_LIKE_VERSION = re.compile(r"v?[0-9]")
_RUNTIME = re.compile(r"""^(?P<indent>\s*)(?:-\s+)?(?P<name>node|python)-version(?P<file>-file)?:[ \t]*(?P<value>.*?)[ \t]*$""")
_LIST_ITEM = re.compile(r"^(?P<indent>\s*)-\s+(?P<item>.*?)\s*$")
_SERIES = re.compile(r"[0-9]+(?:\.[0-9]+)*")
_REQUIREMENT = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==(?P<version>[A-Za-z0-9][A-Za-z0-9.!+_-]*)\s*(?:;[^#]*)?\\?\s*"
)
_FINAL = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,9}){0,3}")
_RELEASE_VERSION = re.compile(r"v?([0-9]+\.[0-9]+\.[0-9]+)(?:-[0-9]+)?")
_SHA = re.compile(r"[0-9a-f]{40}")
NOT_FINAL = "not checked (the pin is not a final release number, so nothing can be said to be newer than it)"


Refused = common.Refused  # (the run cannot be made or cannot be written: one line on standard error, status 2, no stamp)


# ---- what is pinned --------------------------------------------------------------------------------------------------------------------------------------


class ActionPin(NamedTuple):
    repo: str  # owner/name
    path: str | None  # a folder of the repository, for an action that lives in one
    sha: str
    tag: str | None  # the tag the comment after the commit names: its first word, if that is a final version as a whole
    odd_tag: str | None = None  # the first word of the comment when it begins like a version and is not a final one (v4.0.0-beta.1): kept as written, never cut to the final release

    @property
    def name(self) -> str:
        return self.repo + (f"/{self.path}" if self.path else "")


class Workflow(NamedTuple):
    actions: list[ActionPin]
    unpinned: list[str]  # the actions that are not pinned to a commit, as written
    runtimes: dict[str, list[str]]  # every series that is named, each once, in order: {"node": ["24"], "python": ["3.11", "3.12"]}
    unreadable: list[tuple[str, str]]  # (runtime, value as written) for a version that is not a plain series: an expression of a matrix, lts/*, latest...
    version_files: list[tuple[str, str]]  # (runtime, file as written) for a version the workflow reads from a file: node-version-file: .nvmrc


def _plain_series(raw: str) -> str | None:
    """``24`` for ``24``, ``"24.x"`` or ``'24'``; None for anything that is not a series (an expression, ``lts/*``, a range)."""
    series = raw.strip().strip("\"'")
    series = series[:-2] if series.endswith(".x") else series
    return series if _SERIES.fullmatch(series) else None


def _versions_written_at(lines: list[str], index: int, match: re.Match[str]) -> list[str]:
    """The versions that a ``node-version:`` or ``python-version:`` line gives: its own value, the items of a list written in brackets, or the items of the block list under it."""
    value = re.sub(r"[ \t]+#.*$", "", match["value"]).strip()
    if value.startswith("[") and value.endswith("]"):
        return [part.strip() for part in value[1:-1].split(",") if part.strip()]
    if value:
        return [value]
    items: list[str] = []
    for line in lines[index + 1 :]:
        if not line.strip():
            continue
        found = _LIST_ITEM.match(line)
        if found is None or len(found["indent"]) < len(match["indent"]):
            break
        item = re.sub(r"[ \t]+#.*$", "", found["item"]).strip()
        if re.match(r"[A-Za-z_-][\w-]*:(\s|$)", item):
            break  # (an entry that is a mapping, not a version)
        items.append(item)
    return items


def parse_workflow(text: str) -> Workflow:
    """The actions pinned to a commit, those that are not (a local action or a docker image is not an action to pin), and every series of Node and Python of a workflow -- a plain
    series written once, in a list, or in a matrix -- with what could not be read as one."""
    actions: list[ActionPin] = []
    unpinned: list[str] = []
    runtimes: dict[str, list[str]] = {}
    unreadable: list[tuple[str, str]] = []
    version_files: list[tuple[str, str]] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        found = _USES.match(line)
        if found:
            ref = found["ref"].strip("\"'")
            if ref.startswith(("./", "../", "docker://")):
                continue
            pinned = _PINNED.fullmatch(ref)
            if pinned is None:
                if ref not in unpinned:
                    unpinned.append(ref)
                continue
            words = (found["comment"] or "").split(maxsplit=1)
            word = words[0] if words else ""
            tag = word if _TAG.fullmatch(word) else None
            odd = word if tag is None and _LOOKS_LIKE_VERSION.match(word) else None
            pin = ActionPin(pinned["repo"], pinned["path"], pinned["sha"], tag, odd)
            if pin not in actions:
                actions.append(pin)
            continue
        runtime = _RUNTIME.match(line)
        if runtime and runtime["file"]:  # (node-version-file: .nvmrc -- the workflow reads the version from a file, which this check does not follow)
            written = re.sub(r"[ \t]+#.*$", "", runtime["value"]).strip().strip("\"'")
            if written and (runtime["name"], written) not in version_files:
                version_files.append((runtime["name"], written))
        elif runtime:
            for raw in _versions_written_at(lines, index, runtime):
                series = _plain_series(raw)
                if series is None:
                    shown = (runtime["name"], raw.strip().strip("\"'"))
                    if shown not in unreadable:
                        unreadable.append(shown)
                elif series not in runtimes.setdefault(runtime["name"], []):
                    runtimes[runtime["name"]].append(series)
    return Workflow(actions, unpinned, runtimes, unreadable, version_files)


def read_requirements(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """``(pins, loose)`` of a requirements file: the ``name==version`` lines, and the lines that name a package without an exact version."""
    pins: list[tuple[str, str]] = []
    loose: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw)
        if not line.strip() or line.lstrip().startswith("-") or raw[:1] in (" ", "\t"):
            continue  # (an option such as -r or --index-url, or the hash lines that go on from the line before)
        found = _REQUIREMENT.fullmatch(line.strip())
        if found:
            pins.append((found["name"], found["version"]))
        else:
            loose.append(line.strip())
    return pins, loose


def package_json_problems(text: str) -> list[Item]:
    """What a package.json says about itself that makes part of it impossible to check, as lines of the report: that it is not JSON or not an object, that a section of dependencies
    is not an object, and each entry whose version is not text. (:func:`read_package_json` leaves all of that out; this is how it is said.)"""
    try:
        document = json.loads(text)
    except ValueError:
        return [Item("not checked", "- package.json: not checked (package.json is not JSON)")]
    if not isinstance(document, dict):
        return [Item("not checked", "- package.json: not checked (package.json is not a JSON object)")]
    found: list[Item] = []
    for section in ("dependencies", "devDependencies"):
        listed = document.get(section)
        if listed is None:
            continue
        if not isinstance(listed, dict):
            found.append(Item("not checked", f"- package.json: not checked ({section} is not an object)"))
            continue
        found += [Item("not checked", f"- {common.code_span(str(name))} ({section}): not checked (its version is not text)") for name, spec in listed.items() if not isinstance(spec, str)]
    return found


def read_package_json(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """``(pins, loose)`` of a package.json: the dependencies and development dependencies pinned to an exact version, and those given as a range, a tag or an address."""
    try:
        document = json.loads(text)
    except ValueError:
        return [], []
    pins: list[tuple[str, str]] = []
    loose: list[tuple[str, str]] = []
    for section in ("dependencies", "devDependencies"):
        listed = document.get(section) if isinstance(document, dict) else None
        for name, spec in (listed.items() if isinstance(listed, dict) else ()):
            if isinstance(spec, str):
                (pins if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", spec) else loose).append((name, spec))
    return pins, loose


# ---- versions, ages and the rule of 14 days ----------------------------------------------------------------------------------------------------------------


def version_key(text: object) -> tuple[int, ...] | None:
    """A final release number as a tuple of four numbers to compare (``2.5`` is ``2.5.0.0``); None for anything else: a pre-release, a post-release, a tag with a ``v``."""
    if not isinstance(text, str) or _FINAL.fullmatch(text) is None:
        return None
    parts = tuple(int(part) for part in text.split("."))
    return parts + (0,) * (4 - len(parts))


class Candidate(NamedTuple):
    text: str
    key: tuple[int, ...]
    released: datetime.datetime


class Pick(NamedTuple):
    ready: Candidate | None  # the newest version newer than the pin that is old enough
    young: Candidate | None  # the newest version that is too young, if it is newer than the one that is old enough


def age_days(candidate: Candidate, now: datetime.datetime) -> int:
    return max(0, (now - candidate.released).days)


def pick(candidates: Iterable[Candidate], current: tuple[int, ...], now: datetime.datetime) -> Pick:
    """Of the versions newer than ``current``, the newest one that is at least 14 days old, to the second, and the newest that is younger (named only when it is newer than the
    first). A pin that has no number (``version_key`` is None) has nothing to be newer than: it is not compared at all."""
    return _pick([candidate for candidate in candidates if candidate.key > current], now)


def pick_all(candidates: Iterable[Candidate], now: datetime.datetime) -> Pick:
    """The same, of all the versions, when there is no pin to compare with (the newest release of a series, or of the later ones)."""
    return _pick(list(candidates), now)


def _pick(newer: list[Candidate], now: datetime.datetime) -> Pick:
    needed = datetime.timedelta(days=MIN_AGE_DAYS)
    ready = max((c for c in newer if now - c.released >= needed), key=lambda c: c.key, default=None)
    young = max((c for c in newer if now - c.released < needed and (ready is None or c.key > ready.key)), key=lambda c: c.key, default=None)
    return Pick(ready, young)


def _date(value: object) -> datetime.datetime | None:
    try:
        return common.parse_utc(value)
    except ValueError:
        return None


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pypi_candidates(document: Any, name: str) -> list[Candidate]:
    """The final releases of a PyPI project that have a file that is not yanked, each dated by its earliest such file."""
    info = document.get("info") if isinstance(document, dict) else None
    releases = document.get("releases") if isinstance(document, dict) else None
    if not isinstance(info, dict) or _canonical(str(info.get("name", ""))) != _canonical(name) or not isinstance(releases, dict):
        raise common.Unreachable("the answer is not the package that was asked for")
    found = []
    for text, files in releases.items():
        if not isinstance(files, list):
            raise common.Unreachable("the list of releases is damaged")
        key = version_key(text)
        dates = [_date(f.get("upload_time_iso_8601")) for f in files if isinstance(f, dict) and not f.get("yanked")]
        dated = [d for d in dates if d is not None]
        if key is not None and dated:
            found.append(Candidate(text, key, min(dated)))
    return found


def npm_candidates(document: Any, name: str) -> list[Candidate]:
    """The final versions of an npm package that are not deprecated, each with the time it was published."""
    versions = document.get("versions") if isinstance(document, dict) else None
    times = document.get("time") if isinstance(document, dict) else None
    if not isinstance(document, dict) or document.get("name") != name or not isinstance(versions, dict) or not isinstance(times, dict):
        raise common.Unreachable("the answer is not the package that was asked for")
    found = []
    for text, info in versions.items():
        key, released = version_key(text), _date(times.get(text))
        if key is not None and released is not None and not (isinstance(info, dict) and info.get("deprecated")):
            found.append(Candidate(text, key, released))
    return found


def _release_version(text: object) -> str | None:
    found = _RELEASE_VERSION.fullmatch(text) if isinstance(text, str) else None
    return found.group(1) if found else None


def release_candidates(releases: Any) -> list[Candidate]:
    """The final releases in a list of GitHub releases (not drafts, not pre-releases), by the number in their tag or, failing that, in their name."""
    if not isinstance(releases, list):
        raise common.Unreachable("the answer is not a list of releases")
    found = []
    for item in releases:
        if not isinstance(item, dict) or item.get("prerelease") or item.get("draft"):
            continue
        version = _release_version(item.get("tag_name")) or _release_version(item.get("name"))
        released = _date(item.get("published_at"))
        if version is not None and released is not None:
            found.append(Candidate(version, version_key(version) or (), released))
    return found


# ---- the answer for each pin ---------------------------------------------------------------------------------------------------------------------------


@dataclass
class Item:
    """One line of the report. ``status`` is newer, young, current, moved, unreachable, "not checked", or info (a line that is not counted)."""

    status: str
    line: str


def _days(count: int) -> str:
    return f"{count} day{'s' if count != 1 else ''}"


def _released(candidate: Candidate, now: datetime.datetime) -> str:
    return f"released {candidate.released.date().isoformat()}, {_days(age_days(candidate, now))} ago"


def _too_young(candidate: Candidate, now: datetime.datetime) -> str:
    counts_from = (candidate.released + datetime.timedelta(days=MIN_AGE_DAYS)).date().isoformat()
    return f"({_released(candidate, now)}; it counts from {counts_from})"


def _newer_line(label: str, picked: Pick, now: datetime.datetime) -> Item:
    """The line for a pin with something newer: the newest that is old enough, and a still newer one that is too young; or the young one alone."""
    if picked.ready is not None:
        more = f"; a still newer {picked.young.text} is only {_days(age_days(picked.young, now))} old" if picked.young else ""
        return Item("newer", f"{label}newer {picked.ready.text} ({_released(picked.ready, now)}){more}")
    assert picked.young is not None
    return Item("young", f"{label}newer {picked.young.text} is too young {_too_young(picked.young, now)}")


def judge_package(name: str, current: str, candidates: list[Candidate], now: datetime.datetime) -> Item:
    label = f"- `{name}` {current}: "
    key = version_key(current)
    if key is None:
        return Item("not checked", f"{label}{NOT_FINAL}")
    picked = pick(candidates, key, now)
    if picked.ready is None and picked.young is None:
        return Item("current", f"{label}current")
    return _newer_line(label, picked, now)


class NoRelease(Exception):
    """The repository of an action has no release to compare with."""


class Latest(NamedTuple):
    tag: str
    key: tuple[int, ...]
    released: datetime.datetime
    sha: str


def latest_release(fetcher: common.Fetcher, repo: str) -> Latest:
    """The highest final release of a repository (not a pre-release or a draft, with a version number in its tag and a date; of two of one number the later one) and the commit of
    its tag. It is the highest and not the one made last: a patch of an older line, made after the release of a newer one, is not the release to compare a pin with. Raises
    :class:`NoRelease` if the repository has no release, :class:`common.Unreachable` if the answers cannot be had or are not a release with a version, a date and a commit."""
    try:
        releases = fetcher.get_json(RELEASES.format(repo=repo))
    except common.Unreachable as error:
        if error.reason == "HTTP 404":
            raise NoRelease from None
        raise
    if not isinstance(releases, list):
        raise common.Unreachable("the answer is not a list of releases")
    if not releases:
        raise NoRelease
    best: tuple[tuple[int, ...], datetime.datetime, str] | None = None
    for item in releases:
        if not isinstance(item, dict) or item.get("prerelease") or item.get("draft"):
            continue
        tag, released = item.get("tag_name"), _date(item.get("published_at"))
        key = version_key(tag.lstrip("v")) if isinstance(tag, str) and _TAG.fullmatch(tag) else None
        if key is not None and released is not None and (best is None or (key, released) > (best[0], best[1])):
            best = (key, released, tag)
    if best is None:
        raise common.Unreachable("no release has a version number in its tag and a date")
    key, released, tag = best
    commit = fetcher.get_json(COMMIT_OF_TAG.format(repo=repo, tag=urllib.parse.quote(tag, safe="")))
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or _SHA.fullmatch(sha) is None:
        raise common.Unreachable("the answer has no commit")
    return Latest(tag, key, released, sha)


def judge_action(pin: ActionPin, latest: Latest, now: datetime.datetime) -> Item:
    """Compare a pin with the highest final release: current, a tag that moved, or something newer (old enough, or too young)."""
    pinned_key = version_key(pin.tag.lstrip("v")) if pin.tag else None
    label = f"- `{pin.name}`: "
    if pinned_key is not None and latest.key < pinned_key:
        return Item("current", f"{label}current (the latest release, {latest.tag}, is older than the pinned {pin.tag})")
    if latest.sha == pin.sha and (pinned_key is None or latest.key == pinned_key):
        return Item("current", f"{label}current ({latest.tag} at `{latest.sha}`)")
    if pinned_key is not None and latest.key == pinned_key:
        return Item("moved", f"{label}the tag {pin.tag} now points at `{latest.sha}`, not at the pinned `{pin.sha}`")
    candidate = Candidate(latest.tag, latest.key, latest.released)
    old_enough = datetime.timedelta(days=MIN_AGE_DAYS) <= now - latest.released
    if pin.tag is None:
        start = f"{label}pinned `{pin.sha}` (no tag named), the latest release {latest.tag} is at `{latest.sha}`"
        return Item("newer", f"{start} ({_released(candidate, now)})") if old_enough else Item("young", f"{start}, too young {_too_young(candidate, now)}")
    start = f"{label}pinned `{pin.sha}` ({pin.tag}), newer release {latest.tag} at `{latest.sha}`"
    return Item("newer", f"{start} ({_released(candidate, now)})") if old_enough else Item("young", f"{start} is too young {_too_young(candidate, now)}")


def judge_runtime(name: str, series: str, local: str | None, candidates: list[Candidate], now: datetime.datetime) -> list[Item]:
    """The lines for Node or Python: the newest release of the series that is old enough (against the version of this computer), and a later series if there is one."""
    wanted = tuple(int(part) for part in series.split("."))
    size = len(wanted)
    in_series = [c for c in candidates if c.key[:size] == wanted]
    later = [c for c in candidates if c.key[:size] > wanted]
    local_key = version_key(local) if local else None
    line = min(size, 2)  # (the line of a runtime is its major number, and for Python its minor one too)
    other_line = local_key is not None and local_key[:line] != wanted[:line]  # (this computer runs another series than this one: it is not the one to compare with)
    here = f"{local} on this computer, which is another series" if other_line else f"{local} on this computer" if local else "not found on this computer"
    label = f"- {name} {series}.x ({here}): "
    items: list[Item] = []
    best = pick_all(in_series, now).ready
    if other_line:
        local_key = None
    if not in_series:
        items.append(Item("not checked", f"{label}not checked (no release of the series in the list of releases)"))
    elif local_key is None:
        said = f"{best.text} ({_released(best, now)})" if best else "none yet"
        items.append(Item("not checked", f"{label}not checked; the newest release of the series that is {MIN_AGE_DAYS} days old is {said}"))
    else:
        picked = pick(in_series, local_key, now)
        if picked.ready is None and picked.young is None:
            said = f"the newest release of the series that is {MIN_AGE_DAYS} days old is {best.text}" if best else f"no release of the series is {MIN_AGE_DAYS} days old yet"
            items.append(Item("current", f"{label}current ({said})"))
        else:
            items.append(_newer_line(label, picked, now))
    ahead = pick_all(later, now)
    prefix = f"- {name}, later series: "
    if ahead.ready is not None:
        more = f"; a still newer {ahead.young.text} is only {_days(age_days(ahead.young, now))} old" if ahead.young else ""
        items.append(Item("info", f"{prefix}{ahead.ready.text} ({_released(ahead.ready, now)}){more}"))
    elif ahead.young is not None:
        items.append(Item("info", f"{prefix}{ahead.young.text} is too young {_too_young(ahead.young, now)}"))
    return items


# ---- one run -----------------------------------------------------------------------------------------------------------------------------------------


@dataclass
class Section:
    heading: str
    items: list[Item]


class Inputs(NamedTuple):
    actions: list[ActionPin]
    unpinned: list[str]
    runtimes: dict[str, list[str]]
    python: tuple[list[tuple[str, str]], list[str]] | None  # None: the file is not there
    npm: tuple[list[tuple[str, str]], list[tuple[str, str]]] | None
    workflows: bool  # whether there is a folder of workflows
    unreadable: list[tuple[str, str, str]]  # (file, runtime, value as written): a version of Node or Python that is not a plain series
    version_files: list[tuple[str, str, str]]  # (workflow, runtime, file as written): a version that the workflow reads from a file
    problems: dict[str, list[Item]]  # what is amiss in a file, as lines of the report, by part of the report: "actions", "python" and "npm"


def _text(path: Path) -> tuple[str | None, str | None]:
    """``(text, None)`` for a file, or ``(None, why)`` when it is not UTF-8 text (that is a thing to say in the report, not a reason to refuse the run). A file that cannot be read
    at all is an :class:`OSError`, which the caller does refuse for."""
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        return None, f"{path.name} is not UTF-8 text"


def read_inputs(root: Path) -> Inputs:
    """What is pinned under ``root``: its workflows, ``requirements.txt`` and ``package.json``. Raises :class:`Refused` if there is none of the three. A file that is not UTF-8
    text is a line "not checked" in its part of the report, and the rest is checked."""
    folder = root / ".github" / "workflows"
    actions: list[ActionPin] = []
    unpinned: list[str] = []
    runtimes: dict[str, list[str]] = {}
    unreadable: list[tuple[str, str, str]] = []
    version_files: list[tuple[str, str, str]] = []
    problems: dict[str, list[Item]] = {"actions": [], "python": [], "npm": []}
    try:
        files = sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")]) if folder.is_dir() else []
        for path in files:
            text, why = _text(path)
            if text is None:
                problems["actions"].append(Item("not checked", f"- .github/workflows/{path.name}: not checked ({why})"))
                continue
            workflow = parse_workflow(text)
            actions += [pin for pin in workflow.actions if pin not in actions]
            unpinned += [ref for ref in workflow.unpinned if ref not in unpinned]
            for runtime, series_list in workflow.runtimes.items():
                known = runtimes.setdefault(runtime, [])
                known += [series for series in series_list if series not in known]
            unreadable += [(path.name, runtime, raw) for runtime, raw in workflow.unreadable if (path.name, runtime, raw) not in unreadable]
            version_files += [(path.name, runtime, written) for runtime, written in workflow.version_files if (path.name, runtime, written) not in version_files]
        requirements = root / "requirements.txt"
        python = None
        if requirements.is_file():
            text, why = _text(requirements)
            python = read_requirements(text) if text is not None else ([], [])
            if text is None:
                problems["python"].append(Item("not checked", f"- requirements.txt: not checked ({why})"))
        package = root / "package.json"
        npm = None
        if package.is_file():
            text, why = _text(package)
            npm = read_package_json(text) if text is not None else ([], [])
            problems["npm"] += package_json_problems(text) if text is not None else [Item("not checked", f"- package.json: not checked ({why})")]
    except OSError as error:
        raise Refused(f"cannot read the pins under {root.name}: {type(error).__name__}") from None
    if not folder.is_dir() and python is None and npm is None:
        raise Refused(f"nothing to check under {root.name or root}: there is no .github/workflows, requirements.txt or package.json")  # (the name, not the path: this goes in the log)
    return Inputs(actions, unpinned, runtimes, python, npm, folder.is_dir(), unreadable, version_files, problems)


def _unreachable(label: str, error: common.Unreachable) -> Item:
    return Item("unreachable", f"{label}unreachable ({error.reason})")


def check(fetcher: common.Fetcher, inputs: Inputs, local: Mapping[str, str | None], now: datetime.datetime) -> list[Section]:
    """One run: the actions, the Python packages, the npm packages, then Node and Python."""
    # -- actions
    actions: list[Item] = []
    asked: dict[str, Latest | Item] = {}
    for pin in inputs.actions:
        if pin.odd_tag is not None:  # (a pre-release or a build: not a number to compare, and nothing to ask GitHub about)
            actions.append(
                Item("not checked", f"- `{pin.name}`: pinned `{pin.sha}` at the tag {common.code_span(pin.odd_tag)}, which is not a final release number, so not compared with the releases")
            )
            continue
        if pin.repo not in asked:
            try:
                asked[pin.repo] = latest_release(fetcher, pin.repo)
            except NoRelease:
                asked[pin.repo] = Item("not checked", "not checked (the repository has no release to compare with)")
            except common.Unreachable as error:
                asked[pin.repo] = _unreachable("", error)
        answer = asked[pin.repo]
        if isinstance(answer, Item):
            actions.append(Item(answer.status, f"- `{pin.name}`: {answer.line}"))
        else:
            actions.append(judge_action(pin, answer, now))
    actions += [Item("not checked", f"- `{ref}`: not pinned to a commit, so not checked") for ref in inputs.unpinned]
    actions += inputs.problems["actions"]
    if not inputs.workflows:
        actions.append(Item("info", "- .github/workflows is not there"))
    elif not inputs.actions and not inputs.unpinned and not inputs.problems["actions"]:
        actions.append(Item("info", "- no action is pinned to a commit"))
    # -- python packages
    python: list[Item] = []
    if inputs.python is None:
        python.append(Item("info", "- requirements.txt is not there"))
    else:
        pins, loose = inputs.python
        for name, version in pins:
            label = f"- `{name}` {version}: "
            if version_key(version) is None:
                python.append(Item("not checked", f"{label}{NOT_FINAL}"))  # (a pre-release, a post-release or a local build: nothing to ask the registry)
                continue
            try:
                python.append(judge_package(name, version, pypi_candidates(fetcher.get_json(PYPI_PACKAGE.format(name=_canonical(name))), name), now))
            except common.Unreachable as error:
                python.append(_unreachable(label, error))
        python += [Item("not checked", f"- `{line}`: not an exact pin, so not checked") for line in loose]
        python += inputs.problems["python"]
        if not pins and not loose and not inputs.problems["python"]:
            python.append(Item("info", "- no pin in requirements.txt"))
    # -- npm packages
    npm: list[Item] = []
    if inputs.npm is None:
        npm.append(Item("info", "- package.json is not there"))
    else:
        pins, loose = inputs.npm
        for name, version in pins:
            label = f"- `{name}` {version}: "
            try:
                document = fetcher.get_json(NPM_PACKAGE.format(name=urllib.parse.quote(name, safe="@")))
                npm.append(judge_package(name, version, npm_candidates(document, name), now))
            except common.Unreachable as error:
                npm.append(_unreachable(label, error))
        npm += [Item("not checked", f"- `{name}` {spec}: not an exact pin, so not checked") for name, spec in loose]
        npm += inputs.problems["npm"]
        if not pins and not loose and not inputs.problems["npm"]:
            npm.append(Item("info", "- no pin in package.json"))
    # -- node and python
    runtimes: list[Item] = []
    for name, url in RUNTIMES:
        series_list = inputs.runtimes.get(name)
        if not series_list:
            continue
        try:
            candidates = release_candidates(fetcher.get_json(url))  # (one list of the releases, however many series are judged from it)
        except common.Unreachable as error:
            runtimes.append(_unreachable(f"- {name}: ", error))
            continue
        for series in series_list:
            runtimes += judge_runtime(name, series, local.get(name), candidates, now)
    for file_name, runtime, written in inputs.version_files:
        runtimes.append(
            Item(
                "not checked",
                f"- {runtime}-version-file {common.code_span(written)} ({file_name}): not checked (the version is read from a file by the workflow, which this check does not follow)",
            )
        )
    for file_name, runtime, raw in inputs.unreadable:
        runtimes.append(
            Item("not checked", f"- {runtime}-version {common.code_span(raw)} ({file_name}): not checked (it is not a plain series such as 24 or 3.12, so there is nothing to look up)")
        )
    if not runtimes:
        runtimes.append(Item("info", "- no Node or Python version is named in the workflows"))
    return [
        Section("Actions (.github/workflows)", actions),
        Section("Python packages (requirements.txt)", python),
        Section("npm packages (package.json)", npm),
        Section("Node and Python", runtimes),
    ]


def summary(sections: list[Section]) -> str:
    """The counts of the run, in one line (the words that the command prints after its name)."""
    counts = Counter(item.status for section in sections for item in section.items)
    checked = counts["newer"] + counts["young"] + counts["current"] + counts["moved"]
    return (
        f"{counts['newer']} newer ({MIN_AGE_DAYS} days old or more), {counts['young']} newer but too young, {counts['moved']} moved, "
        f"{counts['unreachable']} unreachable, {counts['not checked']} not checked; {checked} pins checked"
    )


def render_report(sections: list[Section], now: datetime.datetime) -> str:
    """The report, in Markdown: pins, versions, commits, dates and the kinds of failure, and no other text from any site."""
    lines = [
        f"# Pins check, {now.astimezone(datetime.timezone.utc).date().isoformat()}",
        "",
        f"Summary: {summary(sections)}.",
        "",
        f"Run at {common.utc_text(now)}. The run changes no pin and reports nothing anywhere: the pins are yours to change. A newer version counts only when it is at least {MIN_AGE_DAYS} days old by its release date; a younger one is named apart, with the day it counts from. If something here needs an issue, open an issue by hand (docs/runbook-weekly.md says when and how).",
    ]
    for section in sections:
        lines += ["", f"## {section.heading}", ""]
        lines += [item.line for item in section.items]
    return "\n".join([*lines, ""])


# ---- the command ---------------------------------------------------------------------------------------------------------------------------------------


def _node_version() -> str | None:
    node = shutil.which("node")
    if node is None:
        return None
    flags = {"creationflags": 0x08000000} if os.name == "nt" else {}  # (no console window flashes up when a scheduled task asks)
    try:
        done = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=NODE_TIMEOUT, check=False, **flags)
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.fullmatch(r"v([0-9]+\.[0-9]+\.[0-9]+)", done.stdout.strip()) if done.returncode == 0 else None
    return found.group(1) if found else None


def local_versions() -> dict[str, str | None]:
    """The Python this script runs under (the project's own, in .venv) and the Node on the path, if there is one."""
    return {"python": platform.python_version(), "node": _node_version()}


def _parser() -> argparse.ArgumentParser:
    parser = common.Parser(
        prog="pins_check.py",
        description="The monthly check of the pins: newer commits of the pinned actions and newer versions (at least 14 days old) of the pinned packages and runtimes. Writes a report; changes no pin; never opens an issue.",
    )
    parser.add_argument("--contact", default=common.DEFAULT_CONTACT, help=f"the page of the site that the user agent points to, which says who runs the check (default: {common.DEFAULT_CONTACT})")
    parser.add_argument("--root", type=common.path_argument, default=ROOT, help="the repository whose pins are read (default: this one)")
    parser.add_argument("--out", type=common.path_argument, help="the folder of the report and the stamp (default: the folder of the checks, outside every worktree: $TRIOFORGE_CHECKS_DIR, else ~/.local/state/trioforge/checks)")
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


def _recorded_local(folder: Path) -> dict[str, str | None]:
    """The versions of Node and Python that a dry run's recorded answers say this computer has (``local`` in replay.json)."""
    try:
        local = json.loads((folder / "replay.json").read_text(encoding="utf-8")).get("local")
    except (OSError, ValueError, AttributeError):
        return {}
    return {name: value for name, value in local.items() if isinstance(value, str)} if isinstance(local, dict) else {}


def run_command(
    args: argparse.Namespace,
    *,
    transport: common.Transport | None,
    clock: Callable[[], float] | None,
    sleep: Callable[[float], None] | None,
    now: Callable[[], datetime.datetime],
    local: Mapping[str, str | None] | None,
) -> str:
    """The run: the report and the stamp are written, and the counts and the place of the report are printed. Returns the text of the line of the log."""
    if args.dry_run is not None and args.out is None:
        raise Refused("a dry run needs --out FOLDER, so that it cannot replace a real report")
    if args.dry_run is not None and common.is_the_real_folder(args.out):
        raise Refused("a dry run cannot write into the folder of the real checks, which would replace a real report and a real stamp; give --out another folder")
    out = args.out if args.out is not None else _default_folder()
    agent = _user_agent(args)
    inputs = read_inputs(args.root)
    if args.dry_run is not None:
        try:
            transport = common.ReplayTransport.from_directory(args.dry_run)
        except ValueError as error:
            raise Refused(str(error)) from None
        virtual = common.VirtualTime()
        clock, sleep = virtual.clock, virtual.sleep
        local = local if local is not None else _recorded_local(args.dry_run)
    elif transport is None:
        transport = common.real_transport()
    fetcher = common.Fetcher(agent, transport=transport, clock=clock, sleep=sleep, honour_robots=False)  # (documented APIs, for programs)
    started = now()
    sections = check(fetcher, inputs, local if local is not None else local_versions(), started)
    report = _write_report(out, started, render_report(sections, started))
    try:
        common.write_stamp(out, NAME, now())  # (last: a run that did not get here leaves no stamp)
    except OSError as error:
        raise Refused(f"cannot write the stamp: {error.strerror or type(error).__name__}") from None
    print(f"{NAME}: {summary(sections)}")
    print(f"report: {_show(report)}")
    return f"{summary(sections)}; report {report.name}"


def main(
    argv: list[str] | None = None,
    *,
    transport: common.Transport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], datetime.datetime] | None = None,
    local_versions: Mapping[str, str | None] | None = None,
) -> int:
    """The command. ``transport``, ``clock``, ``sleep``, ``now`` and ``local_versions`` are for the tests, which replace the network, the wall clock and this computer."""
    when = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
    return common.run_main(
        NAME,
        _parser(),
        argv,
        lambda args: run_command(args, transport=transport, clock=clock, sleep=sleep, now=when, local=local_versions),
        now=when,
    )


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):  # (a console in an old code page loses a character of a line, not the lines after it)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    sys.exit(main())
