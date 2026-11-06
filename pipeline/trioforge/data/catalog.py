"""Build the public catalog: read the cached wiki pages, grade every item on the evidence ladder, write the derived files.

::

    python -m trioforge.data.catalog --wiki sources/eqlwiki/2026-10-14 --client derived/client --out derived [--eqlegendstools sources/eqlegendstools/2026-10-25]

reads

* the wiki cache (``manifest.json``, ``raw/members.json`` and ``raw/batch-*.json.gz`` of one fetch, see
  :mod:`trioforge.sources.eqlwiki`), which must be a finished fetch;
* the client extract (``derived/client``: ``zones.json`` and the manifest that ties it to the game files);
* ``derived/quests.json`` and the hand-written rules ``rules/zone-aliases.json``, ``rules/hand-lists.json``
  and (when it exists) ``rules/community-seen.json``;

and writes, all or nothing, into ``--out``:

* ``catalog.json``: ``{"version", "license", "attribution", "provenance", "items"}``, one item per line,
  sorted by key. An item is :func:`trioforge.data.normalize.normalize`'s item plus ``evidence``, with the zones
  that its page writes as bullets made zones (:func:`trioforge.data.normalize.promote_bullet_zones`);
* ``catalog-summary.json``: counts by level, slot, class and reason, the shields by source (``item_types``),
  the zones the alias table does not know (the most common first), unknown era tags and warnings by code;
* ``catalog-warnings.json``: every parse warning as ``{key, code, field}`` and every page that is not an item;
* ``sources-manifest.json``: item key to ``{title, revid}``, for the credits page (wiki items only; with ``--eqlegendstools`` it also has
  ``eqlegendstools``: item key to ``{title, slug}`` for the items read from that site).

**EQ Legends Tools.** With ``--eqlegendstools DIR`` (a finished fetch of :mod:`trioforge.sources.eqlegendstools`) the items of that
site's zone pages enter the catalog after the wiki pages are parsed: each overrides the wiki's copy of the same item or is added
when the wiki lacks it, see :mod:`trioforge.data.eqlt_merge`; the summary has a section ``eqlegendstools`` with what was done and
every field where the two disagree, and ``provenance.inputs`` names the zone pages and the hash of the fetch.

**Shields.** Item pages rarely say ``Type: Shield``, and held items (crystals, orbs, totems) also fill the off
hand and have an armor class, so the builder settles ``item_type`` and ``item_type_source`` for every item, in this
order.

1. The page states a type: the type stays and the source is ``"statsblock"``.
2. The item fits the off-hand slot alone, or the off hand and the back and no other slot (a shield that is worn on
   the back too), is no weapon, has an armor class above zero and has ``shield``, ``buckler``, ``aegis``,
   ``bulwark`` or ``targe`` anywhere in its name (so ``Battleshield`` counts): ``item_type`` is ``"Shield"``,
   source ``"name"``. An item that also fits the main hand, the range, the neck or any other slot stays a held item.
3. The item's key is in the hand list ``shields``: ``"Shield"``, source ``"hand-list"``.

An item whose key is in the hand list ``not_shields`` is never typed as a shield, whatever its page or its name says.
Everything else keeps ``item_type`` ``null`` and the source ``null``. See :func:`assign_item_types`.

**Class and race lists.** A page that says ``Race: NONE`` (or ``Class: NONE``) states an empty list: nobody may wear
(or use) the item. The list stays empty and the evidence ladder marks the item ``not-for-bis`` with the note
``race NONE`` (``class NONE``). A page with no ``Race:`` line is read as all races, as ever, and says nothing.

**Every page is parsed under a time limit.** A worker process parses and normalizes one page at a time;
a page that takes more than ``--timeout`` seconds (default 10) is skipped as ``timeout``, its worker
is killed and a new one takes over. A page that is not an item (a redirect, a page with no Itempage
template, ...) is skipped with its reason and counted; none becomes a zero-stat item.

**The committed catalog never holds private evidence.** ``--seen PATH`` merges the maintainer's private
list of item keys seen in game (the file the private exporter writes). That is for the CI build and for
private previews, and it is refused unless the output directory is outside every git work tree (this
repository, a worktree of it, another clone: any folder with a ``.git`` entry above the output) or inside the
``build/`` folder of one, with git confirming that the files written there are ignored (default
``build/catalog-with-seen``): never ``derived/``, never any other tracked folder. Folders are compared by what
they are on the disk, so another spelling of the same folder (an extended ``\\\\?\\`` prefix, a share of this
computer, a short name, a link) is refused too. The refusal happens before anything is read or written.

**A patched game client is refused.** Each file in ``derived/client`` records the sha256 of the game files
it was made from; the manifest records the latest. If they differ, the extracts come from different
patches and the build stops, naming the file. Hashes, never modification times.

Exit status: 0 done, 2 refused or failed (one line on stderr, nothing written).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import threading
import zlib
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import trioforge
from trioforge.classes import CLASS_CODES
from trioforge.community import CommunityError, read_document
from trioforge.data.evidence import (
    LEVELS,
    NOT_HIDING_CODES,
    Context,
    EvidenceError,
    HandLists,
    QuestTable,
    Report,
    ambiguous_names,
    classify,
    is_known_zone,
    load_aliases,
    load_hand_lists,
    out_of_era_names,
    title_key,
)
from trioforge.data.jsonio import JsonFileError, load_strict, render
from trioforge.data.normalize import (
    ITEM_TYPE_SOURCES,
    SLOTS,
    normalize,
    promote_bullet_zones,
    sanitize_text,
    validate_item,
)
from trioforge.data.eqlt_merge import merge_eqlegendstools
from trioforge.privacy.textnorm import normalize_unicode
from trioforge.sources.client_tables import commit_files, iso_date, one_line, read_manifest, today_utc
from trioforge.sources.eqlegendstools import HOST as EQLT_HOST
from trioforge.sources.eqlegendstools import ParseError as EqltParseError
from trioforge.sources.eqlegendstools import read_snapshot as read_eqlt_snapshot
from trioforge.sources.eqlwiki import BATCH_SIZE
from trioforge.sources.itempage import Skip, parse_page

__all__ = [
    "ATTRIBUTION",
    "BuildError",
    "GENERATOR",
    "LICENSE",
    "OUTPUT_FILES",
    "SHIELD_NAME",
    "assign_item_types",
    "build_catalog",
    "check_client",
    "check_seen_output",
    "load_community_keys",
    "load_seen_keys",
    "main",
    "parse_and_normalize",
    "parse_pages",
    "read_wiki",
    "validate_catalog",
]

REPO_ROOT = Path(__file__).resolve().parents[3]  # tests point this at a scratch folder
LICENSE = "CC BY-SA 4.0"
GENERATOR = f"trioforge.data.catalog {trioforge.__version__}"
ATTRIBUTION = (
    "Item data adapted from eqlwiki.com (CC BY-SA 4.0) by the eqlwiki contributors; quest giver data compiled by "
    "EQL Tools (https://eqltools.com/sources) from eqlwiki; changes: parsed, normalized, filtered, graded by evidence"
)
OUTPUT_FILES = ("catalog.json", "catalog-summary.json", "catalog-warnings.json", "sources-manifest.json")

PAGE_TIMEOUT = 10.0  # seconds one page may take to parse and normalize
STARTUP_TIMEOUT = 120.0  # seconds a worker may take to start (its imports); not counted against a page
DEFAULT_TARGET = "trioforge.data.catalog:parse_and_normalize"
MAX_UNMAPPED_ZONES = 100  # zones listed in the summary
MAX_EXAMPLES = 20
MAX_SKIPPED_LISTED = 500
_KEY = re.compile(r"(?:w[0-9]{1,15}|r[a-z0-9][a-z0-9-]{0,99})")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SPACES = re.compile(r"\s+")
# The name rule for shields: a substring, in any case ("Battleshield", "Webshield"). ASCII-only folding, like the
# statsblock keys, so that a dotless i or a long s in a name never makes a word.
SHIELD_NAME = re.compile(r"shield|buckler|aegis|bulwark|targe", re.ASCII | re.IGNORECASE)
SHIELD_SLOTS = frozenset({"SECONDARY", "BACK"})  # the slots a shield may fit: the off hand, and for some also the back


class BuildError(Exception):
    """The build was refused or failed. The message is one line and never holds page text."""


# ---- parsing under a time limit --------------------------------------------------------------------


def parse_and_normalize(page: dict) -> tuple:
    """Parse and normalize one page record: ``("item", item)`` or ``("skip", reason)``.

    This is what a worker process runs. ``item`` is checked against the item schema.
    """
    parsed = parse_page(page)
    if isinstance(parsed, Skip):
        return ("skip", parsed.reason)
    item = normalize(parsed)
    validate_item(item)
    return ("item", item)


def _resolve(target: str) -> Callable[[dict], tuple]:
    module, _, name = target.partition(":")
    return getattr(importlib.import_module(module), name)


def _worker_main(connection: Any, target: str) -> None:
    function = _resolve(target)
    connection.send(("ready",))  # imports are done: from here on, the clock is the page's
    while True:
        try:
            page = connection.recv()
        except (EOFError, OSError):
            return
        if page is None:
            return
        try:
            outcome = function(page)
        except Exception as error:  # noqa: BLE001 - a page must never end the worker
            outcome = ("error", type(error).__name__)
        try:
            connection.send(outcome)
        except (OSError, ValueError):
            return


class _Worker:
    """One child process that handles one page at a time and can be killed when a page takes too long."""

    def __init__(self, target: str) -> None:
        context = multiprocessing.get_context("spawn")
        self._connection, child = context.Pipe()
        self._process = context.Process(target=_worker_main, args=(child, target), daemon=True)
        self._process.start()
        child.close()
        try:
            started = self._connection.poll(STARTUP_TIMEOUT) and self._connection.recv() == ("ready",)
        except (EOFError, OSError):
            started = False
        if not started:
            self.kill()
            raise BuildError("a parser worker process did not start")

    def call(self, page: dict, timeout: float) -> tuple:
        try:
            self._connection.send(page)
            if not self._connection.poll(timeout):
                return ("timeout",)
            return self._connection.recv()
        except (EOFError, OSError, ValueError):
            return ("crashed",)

    def kill(self) -> None:
        try:
            self._connection.close()
        except OSError:
            pass
        if self._process.is_alive():
            self._process.kill()
        self._process.join(timeout=5)


def parse_pages(
    pages: Sequence[dict],
    *,
    workers: int | None = None,
    timeout: float = PAGE_TIMEOUT,
    target: str = DEFAULT_TARGET,
) -> list[tuple]:
    """Run ``target`` (``"module:function"``) on every page, each under ``timeout`` seconds.

    Returns one outcome per page, in page order: ``("item", item)``, ``("skip", reason)``, or for a page
    that took too long ``("timeout",)``, for a worker that died ``("crashed",)`` and for a page that made
    the function raise ``("error", name)``. ``workers`` processes run at once (default: up to four);
    ``workers=0`` runs in this process with no time limit.
    """
    if workers is None:
        workers = min(4, os.cpu_count() or 1)
    if workers <= 0 or not pages:
        function = _resolve(target)
        outcomes = []
        for page in pages:
            try:
                outcomes.append(function(page))
            except Exception as error:  # noqa: BLE001
                outcomes.append(("error", type(error).__name__))
        return outcomes
    outcomes: list[tuple | None] = [None] * len(pages)
    numbers = iter(range(len(pages)))
    lock = threading.Lock()
    count = min(workers, len(pages))

    def take() -> int | None:  # the next page number, or None when every page has been handed out
        with lock:
            return next(numbers, None)

    def run() -> None:
        worker = _Worker(target)
        try:
            while (index := take()) is not None:
                outcome = worker.call(pages[index], timeout)
                if outcome[0] in ("timeout", "crashed"):
                    worker.kill()
                    worker = _Worker(target)
                outcomes[index] = outcome
        finally:
            worker.kill()

    with ThreadPoolExecutor(max_workers=count) as pool:
        for future in [pool.submit(run) for _ in range(count)]:
            future.result()
    return [outcome if outcome is not None else ("crashed",) for outcome in outcomes]


# ---- reading the inputs ------------------------------------------------------------------------------


def _sha256_bytes(*chunks: bytes) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _need_file(path: Path, what: str) -> Path:
    if not path.is_file():
        raise BuildError(f"input file missing: {what}")
    return path


def _load_json(path: Path, what: str) -> Any:
    _need_file(path, what)
    try:
        return load_strict(path)
    except JsonFileError as error:
        raise BuildError(str(error)) from error
    except OSError as error:
        raise BuildError(f"cannot read {what}") from error


@dataclass
class WikiSnapshot:
    """The wiki pages of one finished fetch, in the order the fetcher saved them."""

    date: str
    category: str
    pages: list[dict]
    sha256: str


def read_wiki(wiki_dir: str | os.PathLike[str]) -> WikiSnapshot:
    """Read a finished fetch (see :mod:`trioforge.sources.eqlwiki`); :class:`BuildError` if it is not whole.

    The manifest must exist (it is written last), every batch file must exist, parse and hold exactly the page
    ids the member list gives it, and the counts must agree. ``sha256`` identifies the pull: it is the hash of
    the member list and then every batch file.
    """
    root = Path(wiki_dir)
    manifest = _load_json(root / "manifest.json", "the wiki fetch manifest.json (is the fetch finished?)")
    members_path = _need_file(root / "raw" / "members.json", "raw/members.json of the wiki fetch")
    members_doc = _load_json(members_path, "raw/members.json")
    valid = (
        isinstance(manifest, dict)
        and isinstance(manifest.get("date"), str)
        and _ISO_DATE.fullmatch(manifest["date"])
        and all(type(manifest.get(key)) is int for key in ("members", "batches", "pages", "missing"))
        and isinstance(manifest.get("category"), str)
        and isinstance(members_doc, dict)
        and isinstance(members_doc.get("members"), list)
    )
    if not valid:
        raise BuildError("the wiki fetch manifest.json or members.json is not in the form the fetcher writes")
    ids = []
    for member in members_doc["members"]:
        if not isinstance(member, dict) or type(member.get("pageid")) is not int:
            raise BuildError("raw/members.json holds a member with no page id")
        ids.append(member["pageid"])
    if len(ids) != manifest["members"] or manifest["pages"] + manifest["missing"] != manifest["members"]:
        raise BuildError("the wiki fetch manifest.json disagrees with raw/members.json")
    chunks = [ids[start : start + BATCH_SIZE] for start in range(0, len(ids), BATCH_SIZE)]
    if len(chunks) != manifest["batches"]:
        raise BuildError("the wiki fetch has a different number of batches than its manifest says")
    pages: list[dict] = []
    digest = [members_path.read_bytes()]
    for index, chunk in enumerate(chunks):
        path = _need_file(root / "raw" / f"batch-{index:04d}.json.gz", f"raw/batch-{index:04d}.json.gz of the wiki fetch")
        raw = path.read_bytes()
        try:
            data = json.loads(gzip.decompress(raw))
        except (OSError, EOFError, ValueError, zlib.error):
            raise BuildError(f"raw/batch-{index:04d}.json.gz cannot be read; fetch again with --resume") from None
        batch_pages = data.get("pages") if isinstance(data, dict) else None
        if (
            not isinstance(batch_pages, list)
            or data.get("batch") != index
            or data.get("pageids") != chunk
            or [page.get("pageid") if isinstance(page, dict) else None for page in batch_pages] != chunk
        ):
            raise BuildError(f"raw/batch-{index:04d}.json.gz does not hold the pages it should; fetch again with --resume")
        pages.extend(batch_pages)
        digest.append(raw)
    return WikiSnapshot(date=manifest["date"], category=manifest["category"], pages=pages, sha256=_sha256_bytes(*digest))


@dataclass
class ClientZones:
    """The client zone extract the build uses, checked against the manifest that ties it to the game files."""

    flagged: frozenset[int]
    ids: frozenset[int]
    file_sha256: str
    game_date: str


def check_client(client_dir: str | os.PathLike[str]) -> ClientZones:
    """Read ``zones.json`` after checking that every JSON in ``client_dir`` comes from the files the manifest names.

    For each output the manifest lists, the sha256 of each game file recorded inside it must equal the one
    the manifest records for that file; if not, the client was patched between two extracts and
    :class:`BuildError` names the JSON file and the game file. A file the manifest lists but that is missing is
    an error, and so is a manifest that does not list ``zones.json``.
    """
    root = Path(client_dir)
    try:
        inputs, outputs = read_manifest(root)
    except ValueError as error:
        raise BuildError(one_line(error)) from error
    if not outputs:
        raise BuildError("input file missing: manifest.json of the client extract (run trioforge.sources.client_tables)")
    if "zones.json" not in outputs:
        raise BuildError("the client manifest.json does not list zones.json")
    zones_doc: Any = None
    zones_sha = ""
    for name in sorted(outputs):
        path = _need_file(root / name, f"{name} of the client extract")
        document = _load_json(path, name)
        recorded = (document.get("provenance") or {}).get("inputs") if isinstance(document, dict) else None
        if not isinstance(recorded, list) or not recorded:
            raise BuildError(f"{name} records no game file hashes (provenance.inputs)")
        for record in recorded:
            game_file = record.get("file") if isinstance(record, dict) else None
            current = inputs.get(game_file)
            if current is None or current["sha256"] != record.get("sha256"):
                raise BuildError(
                    f"{name} was extracted from a different {game_file} than manifest.json records: "
                    "the game was patched between extracts, so run trioforge.sources.client_tables again"
                )
        if name == "zones.json":
            zones_doc, zones_sha = document, _file_sha256(path)
    zones = zones_doc.get("zones") if isinstance(zones_doc, dict) else None
    if not isinstance(zones, list) or not all(
        isinstance(z, dict) and type(z.get("id")) is int and isinstance(z.get("flagged"), bool) for z in zones
    ):
        raise BuildError("zones.json is not in the form trioforge.sources.client_tables writes")
    game_dates = [r["date"] for r in zones_doc["provenance"]["inputs"] if isinstance(r.get("date"), str)]
    return ClientZones(
        flagged=frozenset(z["id"] for z in zones if z["flagged"]),
        ids=frozenset(z["id"] for z in zones),
        file_sha256=zones_sha,
        game_date=max(game_dates) if game_dates else "",
    )


def load_seen_keys(path: str | os.PathLike[str]) -> frozenset[str]:
    """The item keys in the private seen-flags file (``{"version", "license", "keys": [...]}``)."""
    document = _load_json(Path(path), "the seen-flags file")
    keys = document.get("keys") if isinstance(document, dict) else None
    if not isinstance(keys, list) or not all(isinstance(key, str) and _KEY.fullmatch(key) for key in keys):
        raise BuildError("the seen-flags file must hold an object with a 'keys' list of item keys")
    return frozenset(keys)


def load_community_keys(path: str | os.PathLike[str]) -> frozenset[str]:
    """The item keys accepted from player reports (``rules/community-seen.json``); none if there is no file.

    The file is ``{"version", "reports": [{"key", "kind", "issue", "date", "check"}], "retracted": [{"key", "issue", "date", "reason"}]}``
    and is read strictly (:func:`trioforge.community.read_document`): a field, value or kind that the form does not list is refused, and so is a
    file of the old form, with a line that says how to convert it. The keys of ``reports`` are the answer; the entries of ``retracted`` give none.
    """
    source = Path(path)
    if not source.exists():
        return frozenset()
    try:
        document = read_document(source)
    except CommunityError as error:
        raise BuildError(str(error)) from error
    return frozenset(entry["key"] for entry in document["reports"])


# ---- where the seen flags may be merged -------------------------------------------------------------

# Windows names a path in several ways: the extended prefixes (\\?\C:\x, \\.\C:\x, \\?\UNC\host\share\x) and
# plain text for the same place. The prefixes that only add a spelling are dropped; any other (\\?\Volume{...})
# stays as it is, because the operating system opens it as written and every test below reads the disk.
_NAMESPACE_PREFIX = re.compile(r"[\\/]{2}[?.][\\/](?:(UNC)[\\/]|([A-Za-z]:)(?=[\\/]|$))", re.IGNORECASE)
# The variables that point git at one repository: the output must be asked about in its own.
_GIT_LOCATION_VARIABLES = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_DIR",
        "GIT_GRAFT_FILE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    }
)
_GIT_TIMEOUT = 60.0


def _plain_path(path: str) -> str:
    found = _NAMESPACE_PREFIX.match(path)
    if found is None:
        return path
    if found.group(1):
        return "\\\\" + path[found.end() :]
    return path[found.start(2) :]


def _resolved_path(path: str | os.PathLike[str]) -> str:
    """Where ``path`` really is: absolute, without a namespace prefix, ``..`` folded, links and junctions followed
    as far as the path exists (the rest, which does not exist yet, is appended as written)."""
    return _plain_path(os.path.realpath(_plain_path(os.fspath(path))))


def _file_id(path: str) -> tuple[int, int] | None:
    """The volume and the file number of an existing folder: the same pair is the same folder, whatever name was
    used to reach it (a short name, a share of this computer, a link). None if there is none to read; a file
    number of 0, which some volumes give for everything, proves nothing."""
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return None
    return (info.st_dev, info.st_ino) if info.st_ino else None


def _folder_and_parents(path: str):
    node = path
    while True:
        yield node
        parent = os.path.dirname(node)
        if parent == node:
            return
        node = parent


def _git_ignores(tree: str, relative: Sequence[str]) -> bool:
    """Whether git, run in the work tree ``tree``, ignores every one of these paths (relative to it, ``/`` as the
    separator). False if git cannot say: no git, a folder named ``.git`` that is no repository, a path git does not
    accept, no answer in time. A path that is tracked is not ignored."""
    exe = shutil.which("git")
    if exe is None:
        return False
    environment = {name: value for name, value in os.environ.items() if name not in _GIT_LOCATION_VARIABLES}
    try:
        done = subprocess.run(
            [exe, "-C", tree, "check-ignore", "-z", "--stdin"],
            input=("\0".join(relative) + "\0").encode("utf-8", "surrogateescape"),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    if done.returncode not in (0, 1):
        return False
    answered = {part.decode("utf-8", "surrogateescape") for part in done.stdout.split(b"\0") if part}
    return answered == set(relative)


def check_seen_output(out_dir: str | os.PathLike[str]) -> None:
    """Refuse an output folder for a build with seen flags unless git itself would never commit what is written there.

    The folder must be outside every git work tree, or inside the ``build/`` folder of one with git saying that
    the files written there are ignored. A work tree is any folder with a ``.git`` entry (a clone, a linked
    worktree of any name, a copy kept elsewhere) and this checkout (``REPO_ROOT``) whether or not it has one, found
    by looking at every folder from the output upwards. The folders are compared by what they are on the disk, not
    by how they are written: ``..``, links and junctions are followed, the extended ``\\\\?\\`` prefixes are
    dropped, and a folder that is the checkout under another name (a share of this computer, a short name, a
    different case) is the checkout. :class:`BuildError` otherwise, and when git cannot confirm the answer.
    """
    where = (
        "refused: a build that merges seen flags may only write outside every git work tree, or into the "
        "git-ignored build/ folder of one, never into a tracked folder such as derived/"
    )
    try:
        target = _resolved_path(out_dir)
        repo = _file_id(_resolved_path(REPO_ROOT))
        trees = []
        for node in _folder_and_parents(target):
            if os.path.lexists(os.path.join(node, ".git")) or (repo is not None and _file_id(node) == repo):
                trees.append(node)
    except (OSError, ValueError) as error:  # a name the system cannot read is no place to put private flags
        raise BuildError(where) from error
    for tree in trees:
        parts = os.path.relpath(target, tree).split(os.sep)
        if os.path.normcase(parts[0]) != "build":  # the tree itself, or any other folder of it
            raise BuildError(where)
        if os.path.lexists(os.path.join(tree, ".git")):
            ignored = [("/".join(parts) + "/" + name) for name in OUTPUT_FILES]
            if not _git_ignores(tree, ignored):
                raise BuildError(
                    "refused: git does not say that the files written under build/ are ignored "
                    "(they would not be kept out of a commit)"
                )


# ---- building ------------------------------------------------------------------------------------------


def _skeleton(name: str) -> str:
    return _SPACES.sub(" ", normalize_unicode(name)[0].casefold()).strip()


def _confusable_pairs(items: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """Pairs of item keys whose names differ but whose casefolded, look-alike-folded skeletons are equal."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        groups.setdefault(_skeleton(item["name"]), []).append(item)
    pairs = []
    for group in groups.values():
        for first in range(len(group)):
            for second in range(first + 1, len(group)):
                if group[first]["name"] != group[second]["name"]:
                    pairs.append((group[first]["key"], group[second]["key"]))
    return sorted(pairs)


def _stated_shield(item_type: Any) -> bool:
    return isinstance(item_type, str) and item_type.casefold() == "shield"


def _shield_by_name(item: Mapping[str, Any]) -> bool:
    """The name rule: the off hand alone or with the back (no other slot), no weapon numbers, an armor class above
    zero, a shield word in the name."""
    slots = set(item["slots"])
    return (
        "SECONDARY" in slots
        and slots <= SHIELD_SLOTS
        and item["weapon"] is None
        and (item["stats"].get("AC") or 0) > 0
        and SHIELD_NAME.search(item["name"]) is not None
    )


def assign_item_types(items: Sequence[dict[str, Any]], hand: HandLists) -> dict[str, Any]:
    """Settle ``item_type`` and ``item_type_source`` of every item, in place, and say what was done.

    ``items`` come from :func:`trioforge.data.normalize.normalize`, which has set the source to ``"statsblock"``
    where the page states a type. For an item whose key is in ``hand.not_shields`` nothing makes it a shield: not the
    name, and not a type that the page states (the maintainer has judged the page wrong; then the type and its
    source are ``None``). For any other item with no type, the name rule and then ``hand.shields`` decide, see the
    module docstring. A type the page states is never replaced. The hand list ``shields`` needs no other condition
    than the key.

    Returns the counts for the summary: ``shield_by_source`` (every item typed as a shield, by source),
    ``shield_vetoed`` (items that ``not_shields`` kept from being a shield, which the page or the name would
    otherwise have made one) and ``hand_list_stale`` (entries of ``shields`` and ``not_shields`` whose key is on
    no page of this pull, or whose name is not the name of the item with that key).
    """
    vetoed = 0
    for item in items:
        key = item["key"]
        if key in hand.not_shields:
            if _stated_shield(item["item_type"]):
                item["item_type"] = item["item_type_source"] = None
                vetoed += 1
            elif item["item_type"] is None and _shield_by_name(item):
                vetoed += 1
        elif item["item_type"] is None:
            if _shield_by_name(item):
                item["item_type"], item["item_type_source"] = "Shield", "name"
            elif key in hand.shields:
                item["item_type"], item["item_type_source"] = "Shield", "hand-list"
    by_source = Counter(item["item_type_source"] for item in items if _stated_shield(item["item_type"]))
    names = {item["key"]: title_key(item["name"]) for item in items}
    stale = sum(
        1
        for entries in (hand.shields, hand.not_shields)
        for key, entry in entries.items()
        if names.get(key) != title_key(entry["name"])
    )
    return {
        "shield_by_source": {source: by_source[source] for source in ITEM_TYPE_SOURCES},
        "shield_vetoed": vetoed,
        "hand_list_stale": stale,
    }


def _counts(items: Sequence[Mapping[str, Any]], skipped: Counter) -> dict[str, Any]:
    by_level = Counter(item["evidence"]["level"] for item in items)
    wearable = [item for item in items if item["slots"]]
    wearable_by_level = Counter(item["evidence"]["level"] for item in wearable)
    by_slot: dict[str, Counter] = {slot: Counter() for slot in SLOTS}
    by_class: dict[str, Counter] = {code: Counter() for code in CLASS_CODES}
    for item in wearable:
        level = item["evidence"]["level"]
        for slot in item["slots"]:
            by_slot[slot][level] += 1
        for code in CLASS_CODES if item["classes"] == ["ALL"] else item["classes"]:
            by_class[code][level] += 1
    reasons: Counter = Counter()
    hidden_by_reason: Counter = Counter()
    for item in items:
        codes = {reason["code"].split(":", 1)[0] for reason in item["evidence"]["reasons"]}
        reasons.update(codes)
        if item["evidence"]["level"] == "hidden":
            hidden_by_reason.update(codes - NOT_HIDING_CODES)  # a note, and the record of an outweighed report, hide nothing

    def ordered(counter: Counter) -> dict[str, int]:
        return {key: counter[key] for key in sorted(counter)}

    def by_levels(counter: Counter) -> dict[str, int]:
        return {level: counter[level] for level in LEVELS}

    return {
        "items": len(items),
        "skipped": ordered(skipped),
        "by_level": by_levels(by_level),
        "wearables": len(wearable),
        "wearables_by_level": by_levels(wearable_by_level),
        "by_slot": {slot: by_levels(by_slot[slot]) for slot in SLOTS},
        "by_class": {code: by_levels(by_class[code]) for code in CLASS_CODES},
        "by_reason": ordered(reasons),
        "hidden_by_reason": ordered(hidden_by_reason),
    }


def build_catalog(
    wiki_dir: str | os.PathLike[str],
    client_dir: str | os.PathLike[str],
    out_dir: str | os.PathLike[str] | None = None,
    *,
    seen_path: str | os.PathLike[str] | None = None,
    quests_path: str | os.PathLike[str] | None = None,
    rules_dir: str | os.PathLike[str] | None = None,
    catalog_keys_allowed: Iterable[str] = (),
    eqlegendstools_dir: str | os.PathLike[str] | None = None,
    generated: str | None = None,
    workers: int | None = None,
    timeout: float = PAGE_TIMEOUT,
    target: str = DEFAULT_TARGET,
) -> dict[str, Any]:
    """Build the catalog (see the module docstring) and return the summary document.

    * ``out_dir`` defaults to ``derived/``, or to ``build/catalog-with-seen/`` when ``seen_path`` is given;
      with ``seen_path`` it is checked first (:func:`check_seen_output`) and nothing is read until it passes.
    * ``catalog_keys_allowed`` are the item keys an EQ Legends Tools listing may confirm; empty unless its
      owner has given permission.
    * ``eqlegendstools_dir`` is a finished fetch of :mod:`trioforge.sources.eqlegendstools`: its items override the wiki's copy of
      the same item and add the items the wiki lacks (:mod:`trioforge.data.eqlt_merge`); without it the catalog is the wiki's alone.
    * ``workers``, ``timeout`` and ``target`` are for :func:`parse_pages`.

    Raises :class:`BuildError` if an input is missing, damaged or from a different patch.
    """
    rules = Path(rules_dir) if rules_dir is not None else REPO_ROOT / "rules"
    quests_file = Path(quests_path) if quests_path is not None else REPO_ROOT / "derived" / "quests.json"
    if out_dir is None:
        out = REPO_ROOT / ("build/catalog-with-seen" if seen_path is not None else "derived")
    else:
        out = Path(out_dir)
    if seen_path is not None:
        check_seen_output(out)
    generated = generated or today_utc()

    snapshot = read_wiki(wiki_dir)
    eqlt = None
    if eqlegendstools_dir is not None:
        try:
            eqlt = read_eqlt_snapshot(eqlegendstools_dir)
        except (EqltParseError, OSError, ValueError) as error:  # (a missing folder or file, a damaged manifest or page)
            raise BuildError(f"the EQ Legends Tools fetch {eqlegendstools_dir} ({type(error).__name__}): {one_line(error)}") from error
    client = check_client(client_dir)
    try:
        aliases = load_aliases(_need_file(rules / "zone-aliases.json", "rules/zone-aliases.json"), zone_ids=client.ids)
        hand = load_hand_lists(_need_file(rules / "hand-lists.json", "rules/hand-lists.json"))
    except EvidenceError as error:
        raise BuildError(f"{error.source}: {len(error.problems)} problem(s), first: {error.problems[0]}") from error
    quests_doc = _load_json(quests_file, "derived/quests.json")
    try:
        quests = QuestTable.from_data(quests_doc, "quests.json")
    except EvidenceError as error:
        raise BuildError(f"quests.json: {error.problems[0]}") from error
    community_file = rules / "community-seen.json"
    community = load_community_keys(community_file)
    seen = load_seen_keys(seen_path) if seen_path is not None else frozenset()

    outcomes = parse_pages(snapshot.pages, workers=workers, timeout=timeout, target=target)
    items: list[dict[str, Any]] = []
    skipped: Counter = Counter()
    skipped_list: list[dict[str, Any]] = []
    for page, outcome in zip(snapshot.pages, outcomes):
        if outcome[0] == "item":
            items.append(outcome[1])
            continue
        reason = outcome[1] if outcome[0] == "skip" else ("error" if outcome[0] == "crashed" else outcome[0])
        skipped[reason] += 1
        if len(skipped_list) < MAX_SKIPPED_LISTED:
            skipped_list.append(
                {"pageid": page.get("pageid") if type(page.get("pageid")) is int else None,
                 "title": sanitize_text(page["title"]) if isinstance(page.get("title"), str) else None,
                 "reason": reason}
            )  # fmt: skip
    eqlt_report = None
    if eqlt is not None:
        try:
            items, eqlt_report = merge_eqlegendstools(items, eqlt.items)
        except ValueError as error:
            raise BuildError(f"the EQ Legends Tools items: {one_line(error)}") from error
    keys = [item["key"] for item in items]
    if len(set(keys)) != len(keys):
        raise BuildError("two pages give the same item key")
    item_types = assign_item_types(items, hand)

    context = Context(
        flagged=client.flagged,
        aliases=aliases,
        hand=hand,
        quests=quests,
        seen_keys=seen,
        community_keys=community,
        catalog_keys_allowed=frozenset(catalog_keys_allowed),
        out_of_era_names=out_of_era_names(items, hand),
        ambiguous_names=ambiguous_names(items),
    )
    report = Report()
    for item in items:
        # a drop list that writes its zones as bullets: the alias table of this build says which bullets are zones
        item["sources"]["drops"] = promote_bullet_zones(item["sources"]["drops"], lambda name: is_known_zone(name, context))
        item["evidence"] = classify(item, context, report)
    items.sort(key=lambda item: item["key"])

    inputs = [
        {
            "file": f"https://eqlwiki.com/index.php?title={snapshot.category.replace(' ', '_')}",
            "sha256": snapshot.sha256,
            "date": snapshot.date,
        },
        {"file": "derived/client/zones.json", "sha256": client.file_sha256, "date": client.game_date},
        {"file": "derived/quests.json", "sha256": _file_sha256(quests_file), "date": _first_input_date(quests_doc, generated)},
        {"file": "rules/zone-aliases.json", "sha256": _file_sha256(rules / "zone-aliases.json"), "date": _version_of(rules / "zone-aliases.json", generated)},
        {"file": "rules/hand-lists.json", "sha256": _file_sha256(rules / "hand-lists.json"), "date": _version_of(rules / "hand-lists.json", generated)},
    ]  # fmt: skip
    if eqlt is not None:
        for zone in eqlt.zones:  # (one record for each zone page; the hash is that of the whole fetch: the zone pages and the item pages)
            inputs.append({"file": f"https://{EQLT_HOST}/zones/{zone}/", "sha256": eqlt.sha256, "date": eqlt.date})
    if community_file.exists():
        inputs.append(
            {"file": "rules/community-seen.json", "sha256": _file_sha256(community_file), "date": _version_of(community_file, generated)}
        )
    provenance = {"inputs": sorted(inputs, key=lambda record: record["file"]), "generator": GENERATOR, "generated": generated}

    pairs = _confusable_pairs(items)
    warning_codes: Counter = Counter()
    warnings = []
    overflow = 0
    for item in items:
        overflow += item["parse_warnings_overflow"]
        for warning in item["parse_warnings"]:
            warning_codes[warning["code"]] += 1
            warnings.append({"key": item["key"], "code": warning["code"], "field": warning["field"]})
    unmapped = sorted(report.unmapped_zones.items(), key=lambda pair: (-pair[1], pair[0]))
    community_unknown = len(community - set(keys))
    counts = _counts(items, skipped)
    summary = {
        "provenance": provenance,
        "license": LICENSE,
        "counts": counts,
        "item_types": item_types,
        "unmapped_zones": [{"zone": zone, "items": count} for zone, count in unmapped[:MAX_UNMAPPED_ZONES]],
        "unmapped_zone_total": len(unmapped),
        "unknown_era_tags": {tag: report.unknown_eras[tag] for tag in sorted(report.unknown_eras)},
        "community_unknown": community_unknown,
        "warnings": {
            "parse_by_code": {code: warning_codes[code] for code in sorted(warning_codes)},
            "items_with_parse_warnings": sum(1 for item in items if item["parse_warnings"]),
            "parse_warnings_overflow": overflow,
            "build": {
                "confusable-names": len(pairs),
                "unknown-era-tag": sum(report.unknown_eras.values()),
                "unmapped-zone": len(unmapped),
                "community-unknown": community_unknown,
            },
        },
        "confusable_names": {"warning": "confusable-names", "pairs": len(pairs), "examples": [list(pair) for pair in pairs[:MAX_EXAMPLES]]},
    }  # fmt: skip
    if eqlt_report is not None:
        summary["eqlegendstools"] = eqlt_report
        summary["warnings"]["build"]["eqlegendstools-skipped"] = len(eqlt_report["skipped"])  # (pages of new items that state no class or slot: left out, see eqlt_merge)
    if seen_path is not None:
        summary["seen"] = {"keys": len(seen), "unknown": len(seen - set(keys))}

    texts = {
        "catalog.json": render(
            {"version": snapshot.date, "license": LICENSE, "attribution": ATTRIBUTION, "provenance": provenance, "items": items},
            per_line=("items",),
        ),
        "catalog-summary.json": render(summary),
        "catalog-warnings.json": render(
            {"provenance": provenance, "license": LICENSE, "warnings": warnings, "skipped": skipped_list},
            per_line=("warnings", "skipped"),
        ),
        "sources-manifest.json": render(
            {
                "provenance": provenance,
                "license": LICENSE,
                "attribution": ATTRIBUTION,
                "items": {item["key"]: {"title": item["wiki"]["title"], "revid": item["wiki"]["revid"]} for item in items if item["wiki"] is not None},
                **(
                    {"eqlegendstools": {item["key"]: {"title": item["name"], "slug": item["origin"]["slug"]} for item in items if "origin" in item}}
                    if eqlt is not None
                    else {}
                ),
            },
            per_line=("items",),
        ),
    }
    try:
        commit_files(out, texts, last="catalog.json")
    except (OSError, ValueError) as error:
        raise BuildError(f"cannot write the catalog: {one_line(error)}") from error
    return summary


def _first_input_date(document: Any, fallback: str) -> str:
    inputs = ((document.get("provenance") or {}).get("inputs")) if isinstance(document, dict) else None
    if isinstance(inputs, list) and inputs and isinstance(inputs[0], dict) and isinstance(inputs[0].get("date"), str):
        return inputs[0]["date"]
    return fallback


def _version_of(path: Path, fallback: str) -> str:
    try:
        version = load_strict(path).get("version")
    except (JsonFileError, OSError, AttributeError):
        return fallback
    return version if isinstance(version, str) and _ISO_DATE.fullmatch(version) else fallback


def validate_catalog(document: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` unless ``document`` is a catalog: its top-level fields, sorted unique keys, an
    ``evidence`` on every item and every item valid against the item schema."""
    expected = ["version", "license", "attribution", "provenance", "items"]
    if list(document) != expected:
        raise ValueError(f"a catalog has the fields {', '.join(expected)} in that order")
    if document["license"] != LICENSE:
        raise ValueError(f"the licence must be {LICENSE}")
    items = document["items"]
    keys = [item["key"] for item in items]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise ValueError("items must be sorted by key, each key once")
    for item in items:
        if "evidence" not in item:
            raise ValueError(f"{item['key']} has no evidence")
        validate_item(item)
        if (item["item_type"] is None) != (item["item_type_source"] is None):
            raise ValueError(f"{item['key']}: item_type and item_type_source must both be set or both be null")


# ---- the command line --------------------------------------------------------------------------------


def _print_summary(summary: Mapping[str, Any], out: Path) -> None:
    counts = summary["counts"]
    level = counts["by_level"]
    print(f"catalog: {counts['items']} items -> {out}")
    print("by level: " + ", ".join(f"{name} {level[name]}" for name in LEVELS))
    wear = counts["wearables_by_level"]
    print(f"wearables ({counts['wearables']}): " + ", ".join(f"{name} {wear[name]}" for name in LEVELS))
    types = summary["item_types"]
    shields = types["shield_by_source"]
    print(f"shields ({sum(shields.values())}): " + ", ".join(f"{source} {n}" for source, n in shields.items()))
    print(f"hand lists: {types['shield_vetoed']} vetoed, {types['hand_list_stale']} stale")
    if counts["skipped"]:
        print("skipped pages: " + ", ".join(f"{reason} {n}" for reason, n in counts["skipped"].items()))
    print("hidden because: " + ", ".join(f"{code} {n}" for code, n in counts["hidden_by_reason"].items()))
    print(f"unmapped zone names: {summary['unmapped_zone_total']}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.data.catalog",
        description="Build the public catalog from a finished eqlwiki fetch and the client extract.",
    )
    parser.add_argument("--wiki", required=True, type=Path, help="a finished fetch, e.g. sources/eqlwiki/2026-10-14")
    parser.add_argument("--client", required=True, type=Path, help="the client extract, derived/client")
    parser.add_argument(
        "--eqlegendstools",
        type=Path,
        help="a finished EQ Legends Tools fetch, e.g. sources/eqlegendstools/2026-10-25: its items override the wiki's copy and add what the wiki lacks",
    )
    parser.add_argument("--out", type=Path, help="output folder (default derived/, or build/catalog-with-seen/ with --seen)")
    parser.add_argument("--seen", type=Path, help="private seen-flags file: CI and private previews only, never derived/")
    parser.add_argument("--quests", type=Path, help="derived/quests.json")
    parser.add_argument("--rules", type=Path, help="the folder with zone-aliases.json and hand-lists.json (default rules/)")
    parser.add_argument("--date", type=iso_date, help="generation date, YYYY-MM-DD (default: today in UTC)")
    parser.add_argument("--workers", type=int, help="parser processes (default up to 4; 0 = no time limit, in this process)")
    parser.add_argument("--timeout", type=float, default=PAGE_TIMEOUT, help="seconds one page may take (default 10)")
    args = parser.parse_args(argv)
    try:
        summary = build_catalog(
            args.wiki,
            args.client,
            args.out,
            seen_path=args.seen,
            quests_path=args.quests,
            rules_dir=args.rules,
            eqlegendstools_dir=args.eqlegendstools,
            generated=args.date,
            workers=args.workers,
            timeout=args.timeout,
        )
    except BuildError as error:
        print(f"error: {one_line(error)}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"error: {one_line(error)}", file=sys.stderr)
        return 2
    out = args.out or REPO_ROOT / ("build/catalog-with-seen" if args.seen else "derived")
    for skipped in (summary.get("eqlegendstools") or {}).get("skipped", ()):
        print(
            f"warning: EQ Legends Tools page {skipped['slug']} ({skipped['name']}) is left out of the catalog: its tooltip states no {' and no '.join(skipped['missing'])} line, "
            "and the item has no wiki copy to take it from",
            file=sys.stderr,
        )
    _print_summary(summary, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
