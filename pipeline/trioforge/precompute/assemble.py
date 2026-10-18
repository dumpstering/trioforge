"""The release folder and its asset: which files ship, ``release.json``, the pointer in git, and the one ``tar.gz``.

A **release** is the folder of results of every trio of the grid (the files :mod:`trioforge.precompute.shards` documents, ``items.json`` of the
folder beside them) plus a ``release.json``, packed into one ``tar.gz`` that the site build later unpacks into a results folder. This module is
light on purpose: it does no solving, so the report of a release (:mod:`trioforge.reports.results_diff`) and the checks can use it.

**What ships.** :func:`stage` puts exactly the files of a release into a new folder, by an allowlist of names: the item table, and for each trio the
four shards, ``defaults.json``, ``robust.json``, the bundle ``engine-l<level>.json``, the runner-up files of the roles and their index. The ``chunks/``
folder of a trio (its chunk files carry the fingerprint of the inputs, the seen flags among them) is never staged, and any other file in a trio's
folder is refused where it is found. Files are linked, not copied, where the volume allows it (a release is hundreds of megabytes), and a copy is
checked against its source. :func:`check_clean` then reads every staged file for the two things that must never be in a release: the reason the
catalog builder gives an item the maintainer has seen, and a field named ``fingerprint``. (The ``inputs`` of the bundles and of the item table, the
digest of the public catalog and the evidence levels, is what the site build compares and is allowed: it says nothing a level does not.)

**``release.json``** is inside the asset and holds what the release is: the tag, ``catalog_date`` (the day of the wiki snapshot; ``release`` is the tag,
which is the day of the release), the SHA-256 of the public catalog the seen flags were merged onto, the rules version and the rules (their values and
levels), the code hash (the hash of the code the chunks are made under and of the code that writes the files of a trio: :func:`code_hash`), the solver options,
the trios with the tiers each has, the sample of the parity suite that the release was held to (``parity_sample``, ``i/n``), the **evidence map** (item key to
evidence level) and a random snapshot id. The evidence map is public at the granularity of a release and nowhere else.

**``releases/<tag>.json``**, the pointer the maintainer commits, holds only the SHA-256 of the asset, the SHA-256 of the catalog, the rules version, the
code hash, the solver options, ``catalog_date`` and the snapshot id (with the tag and the format number). It is made from the release document, so that
the two cannot disagree, and it never holds the evidence map, a trio or an item.

**The snapshot id** is drawn at random for each release (:func:`new_snapshot_id`); it is not derived from the seen flags and no hash of them is
published, because a hash of a short list of item keys can be tried against guesses.

**The asset** (:func:`pack`) is the same bytes for the same folder: files only, sorted, flat names (the asset unpacks into a results folder), no dates,
no owners. :func:`verify_asset` holds it to the manifest of the folder that was scanned, and :func:`extract` unpacks one safely.
"""

from __future__ import annotations

import datetime
import gzip
import hashlib
import itertools
import os
import re
import secrets
import shutil
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trioforge.classes import CLASS_CODES
from trioforge.data.jsonio import JsonFileError, load_strict, render
from trioforge.precompute import shards
from trioforge.site.data import ROLES
from trioforge.sources.client_tables import commit_files

__all__ = [
    "FORMAT",
    "ITEMS_FILE",
    "LEVELS",
    "POINTER_KEYS",
    "RELEASE_FILE",
    "RELEASE_KEYS",
    "ReleaseRefused",
    "StageReport",
    "TAG_PATTERN",
    "WRITER_FILES",
    "check_clean",
    "check_release_document",
    "check_tag",
    "code_hash",
    "combine_code_hashes",
    "evidence_map",
    "extract",
    "grid_trios",
    "is_release_file",
    "is_trio_slug",
    "manifest",
    "new_snapshot_id",
    "pack",
    "pointer_document",
    "read_pointer",
    "read_release_json",
    "release_document",
    "stage",
    "verify_asset",
    "write_pointer",
    "write_release_json",
    "writer_files",
    "writer_hash",
]

FORMAT = 1
#: the pattern of a release tag, as the deploy checks it: ``data-YYYY-MM-DD`` and an optional ``-N`` for a second release of a day
TAG_PATTERN = r"^data-\d{4}-\d{2}-\d{2}(-\d+)?$"
_TAG = re.compile(TAG_PATTERN, re.ASCII)  # (ASCII: a text pattern's \d matches the digits of every script, and a tag has none of those)
RELEASE_FILE = "release.json"
ITEMS_FILE = shards.ITEMS_NAME
LEVELS = ("strict", "wiki", "disputed", "hidden")  # the evidence levels of the catalog
#: the fields of ``release.json``, in order
RELEASE_KEYS = (
    "format", "release", "catalog_date", "catalog_sha256", "rules_version", "rules", "code_hash", "solver", "build_options", "level", "game_patch",
    "trial", "parity_sample", "trios", "evidence", "snapshot_id",
)  # fmt: skip
#: the fields of ``releases/<tag>.json``, in order: what the deploy compares, and nothing that says which items or trios there are
POINTER_KEYS = (
    "format", "release", "asset_sha256", "catalog_sha256", "catalog_date", "rules_version", "code_hash", "solver", "build_options", "snapshot_id",
)  # fmt: skip

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SNAPSHOT = re.compile(r"[0-9a-f]{32}")
_PARITY_SAMPLE = re.compile(r"([0-9]{1,6})/([1-9][0-9]{0,5})")  # i/n: the chunks i, i+n, i+2n ... of the parity suite
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ITEM_KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,99}")
_SLUG = re.compile(r"[a-z]{3}-[a-z]{3}-[a-z]{3}")
_ENGINE_FILE = re.compile(re.escape(shards.ENGINE_PREFIX) + r"[1-9][0-9]{0,2}\.json")
_RESERVED = re.compile(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", re.IGNORECASE)  # device names Windows keeps for itself
#: what no file of a release may hold: the reason of an item the maintainer has seen, and a field called fingerprint
_SEEN_REASON = re.compile(rb"seen-in-game", re.IGNORECASE)
_FINGERPRINT_FIELD = re.compile(rb'"fingerprint"\s*:', re.IGNORECASE)
MAX_MEMBER = 1 << 30  # the largest file :func:`extract` writes (a shard is 200 KB; nothing of a release is near this)


class ReleaseRefused(Exception):
    """A release, or a step of making one, is refused. The message is one line that says what and where."""


# ---- the tag, the grid and the date --------------------------------------------------------------------------------------------


def _calendar(text: Any) -> bool:
    if not isinstance(text, str) or _DATE.fullmatch(text) is None:
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def check_tag(tag: Any) -> str:
    """The tag, if it is ``data-YYYY-MM-DD`` (a real date) with an optional ``-N`` (:data:`TAG_PATTERN`); :class:`ReleaseRefused` otherwise."""
    if isinstance(tag, str) and _TAG.fullmatch(tag) is not None and _calendar(tag[len("data-") : len("data-") + 10]):
        return tag
    shown = tag if isinstance(tag, str) and tag.isprintable() and len(tag) <= 40 else "that"
    raise ReleaseRefused(f"{shown!r} is not a release tag: use data-YYYY-MM-DD, and -N after it for a second release of a day (data-2026-10-17-2)")


def grid_trios() -> tuple[str, ...]:
    """The 560 trios of the grid as the folder of each is named, in class order (``war-clr-pal`` first, ``mag-enc-bst`` ... ``enc-bst-ber`` last)."""
    return tuple("-".join(code.lower() for code in trio) for trio in itertools.combinations(CLASS_CODES, 3))


def is_trio_slug(slug: Any) -> bool:
    """Whether ``slug`` is the folder name of a trio: three class codes in lower case, joined by ``-``, in class order."""
    if not isinstance(slug, str) or _SLUG.fullmatch(slug) is None:
        return False
    order = [CLASS_CODES.index(part.upper()) if part.upper() in CLASS_CODES else -1 for part in slug.split("-")]
    return -1 not in order and order == sorted(set(order))


# ---- the files of a release --------------------------------------------------------------------------------------------------------


def is_release_file(name: str) -> bool:
    """Whether ``name`` (a path relative to a release folder, with ``/``) is a file a release has: the item table, ``release.json``, or a file of a
    trio's folder (the shards, the defaults, the seals, a bundle, a runner-up file or the index of them)."""
    if name in (ITEMS_FILE, RELEASE_FILE):
        return True
    slug, _, rest = name.partition("/")
    return is_trio_slug(slug) and _is_trio_file(rest)


def _is_trio_file(rest: str) -> bool:
    if rest in shards.OUTPUT_NAMES or _ENGINE_FILE.fullmatch(rest) is not None:
        return True
    folder, _, leaf = rest.partition("/")
    if folder != shards.RUNNERUP_DIR or "/" in leaf:
        return False
    return leaf == "index.json" or (leaf.endswith(".json") and leaf.removesuffix(".json") in ROLES)


def _is_link(path: str | os.PathLike[str]) -> bool:
    return os.path.islink(path) or os.path.isjunction(path)


def _trio_files(folder: Path, slug: str) -> list[tuple[str, Path]]:
    """``(name, path)`` of every file of a trio's folder that ships, the ``chunks/`` folder left out; a file that does not ship is refused."""
    found: list[tuple[str, Path]] = []
    for here, dirs, files in os.walk(folder, followlinks=False):
        relative = Path(here).relative_to(folder)
        if relative == Path("."):
            dirs[:] = [name for name in dirs if name != "chunks"]  # the chunk files carry the fingerprint of the inputs: they stay in build/
        for name in sorted(dirs):
            if _is_link(Path(here, name)):
                raise ReleaseRefused(f"{slug}/{(relative / name).as_posix()}: a link, and a release holds files only")
        for name in sorted(files):
            path = Path(here, name)
            inside = (relative / name).as_posix()
            if _is_link(path):
                raise ReleaseRefused(f"{slug}/{inside}: a link, and a release holds files only")
            if not _is_trio_file(inside):
                raise ReleaseRefused(f"{slug}/{inside}: not a file of a release (a trio's folder holds its shards, defaults, seals, bundle and runner-ups)")
            found.append((f"{slug}/{inside}", path))
    return found


@dataclass(frozen=True)
class StageReport:
    """What :func:`stage` did: the trios staged, the trios that had no folder, and the files (``linked`` or ``copied``) and their bytes."""

    trios: tuple[str, ...]
    missing: tuple[str, ...]
    files: int
    bytes: int
    linked: int
    copied: int


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stage(results: str | os.PathLike[str], trios: Sequence[str], staging: str | os.PathLike[str]) -> StageReport:
    """Put the files of a release into the new folder ``staging``: ``items.json`` of ``results`` and the files of each trio's folder (see the module
    docstring). A trio with no folder is reported in ``missing`` (the checks refuse it); a file that does not ship, or a link, is refused before anything
    is made, and a failure part way leaves ``staging`` as it was found. Files are hard-linked where the volume allows and copied otherwise; a copy is
    compared with its source."""
    root, target = Path(results), Path(staging)
    if target.exists() and any(target.iterdir()):
        raise ReleaseRefused(f"the staging folder {target.name} is not empty")
    table = root / ITEMS_FILE
    if not table.is_file() or _is_link(table):
        raise ReleaseRefused(f"{ITEMS_FILE}, the item table of the results, is not in {root.name}")
    plan: list[tuple[str, Path]] = [(ITEMS_FILE, table)]
    present: list[str] = []
    missing: list[str] = []
    for slug in dict.fromkeys(trios):
        if not is_trio_slug(slug):
            raise ReleaseRefused(f"{slug!r} is not the folder of a trio (three class codes in class order, such as pal-mnk-ber)")
        folder = root / slug
        if _is_link(folder):
            raise ReleaseRefused(f"{slug}: a link, and a release holds files only")
        if not folder.is_dir():
            missing.append(slug)
            continue
        present.append(slug)
        plan.extend(_trio_files(folder, slug))
    made = not target.exists()
    target.mkdir(parents=True, exist_ok=True)
    linked = copied = size = 0
    try:
        for name, source in plan:
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, destination)
            except OSError:
                destination.unlink(missing_ok=True)
                shutil.copyfile(source, destination)
                if destination.stat().st_size != source.stat().st_size or _sha256_of(destination) != _sha256_of(source):
                    raise ReleaseRefused(f"the copy {name} differs from {source.name} of the results") from None
                copied += 1
            else:
                linked += 1
            size += destination.stat().st_size
    except BaseException:
        if made:
            shutil.rmtree(target, ignore_errors=True)
        else:
            for child in list(target.iterdir()):
                shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
        raise
    return StageReport(tuple(present), tuple(missing), len(plan), size, linked, copied)


def _walk(folder: Path) -> list[str]:
    """The names of the files under ``folder``, sorted; a link, or anything but a file, is refused."""
    names: list[str] = []
    for here, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs:
            if _is_link(Path(here, name)):
                raise ReleaseRefused(f"{Path(here, name).relative_to(folder).as_posix()}: a link, and a release holds files only")
        for name in files:
            path = Path(here, name)
            shown = path.relative_to(folder).as_posix()
            if _is_link(path) or not path.is_file():
                raise ReleaseRefused(f"{shown}: not a plain file, and a release holds files only")
            names.append(shown)
    return sorted(names)


def manifest(folder: str | os.PathLike[str]) -> dict[str, tuple[int, str]]:
    """``{name: (size, sha256)}`` of every file under ``folder``: what was checked and scanned, for :func:`verify_asset`."""
    root = Path(folder)
    return {name: ((root / name).stat().st_size, _sha256_of(root / name)) for name in _walk(root)}


def check_clean(folder: str | os.PathLike[str]) -> int:
    """Check every file under ``folder`` for being a file of a release and for what no release holds: the reason of an item the maintainer has seen
    (``seen-in-game``) and a field named ``fingerprint``. Returns the number of files; :class:`ReleaseRefused` names the first file at fault."""
    root = Path(folder)
    names = _walk(root)
    for name in names:
        if not is_release_file(name):
            raise ReleaseRefused(f"{name}: not a file of a release")
        data = (root / name).read_bytes()
        if _SEEN_REASON.search(data):
            raise ReleaseRefused(f"{name}: names the reason of an item seen in game, which only a build made with the private flags has")
        if _FINGERPRINT_FIELD.search(data):
            raise ReleaseRefused(f"{name}: has a fingerprint field, and no fingerprint is published")
    return len(names)


# ---- the evidence map -----------------------------------------------------------------------------------------------------------------


def evidence_map(table: Mapping[str, Any]) -> dict[str, str]:
    """``{item key: evidence level}`` of every record of an item table (``items.json``: the exporter's :func:`trioforge.export.browser.items`), in key order.

    A record is known by its ``key``, else ``w`` and its page id. The levels are the table's own (the seen flags are merged into them, and nothing
    in the table says that a flag was)."""
    records = table.get("items") if isinstance(table, Mapping) else None
    if not isinstance(records, list):
        raise ReleaseRefused("the item table has no list of items")
    found: dict[str, str] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ReleaseRefused("the item table has a record that is not an object")
        key = record.get("key") or (f"w{record['id']}" if isinstance(record.get("id"), int) else None)
        evidence = record.get("evidence")
        level = evidence.get("level") if isinstance(evidence, Mapping) else None
        if not isinstance(key, str) or level not in LEVELS:
            raise ReleaseRefused(f"the item table has a record with no key or no evidence level ({key if isinstance(key, str) else 'unnamed'})")
        if key in found:
            raise ReleaseRefused(f"the item table lists {key} twice")
        found[key] = level
    return dict(sorted(found.items()))


# ---- release.json and the pointer ------------------------------------------------------------------------------------------------------


def new_snapshot_id() -> str:
    """A fresh random snapshot id (32 hex digits): drawn for each release, never derived from anything."""
    return secrets.token_hex(16)


#: the source files, relative to the package, that write or shape a published file of a trio: the runner that writes the files, the shards, the defaults
#: and the runner-ups, the seals and flip notes, the bundle and the item table, the strict-JSON writer that sets their bytes, and the scope that decides which
#: tiers a trio has. (The chunks are made under the other code hash, :func:`trioforge.precompute.grid._code_hash`: a change here writes the files of a finished
#: trio again from its chunks and solves nothing.) A test follows what these files import and fails for a module that is neither hashed nor explained.
WRITER_FILES = (
    "data/jsonio.py", "export/browser.py", "precompute/__init__.py", "precompute/engine.py", "precompute/seals.py", "precompute/shards.py", "scope.py",
)  # fmt: skip


def writer_files() -> list[Path]:
    """The files of :data:`WRITER_FILES`, in the fixed order they are hashed in."""
    root = Path(__file__).resolve().parents[1]
    return [root / name for name in WRITER_FILES]


def writer_hash() -> str:
    """The SHA-256 of the source files of :func:`writer_files` (names and contents, line endings aside)."""
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in writer_files():
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def combine_code_hashes(chunks: str, writers: str) -> str:
    """The code hash of a release from the hash of the code the chunks are made under and the hash of the code that writes the files (:func:`code_hash` hashes the
    source files now; the release build hashes them once, at its start, and puts this in ``release.json``)."""
    return hashlib.sha256(f"chunks {chunks}\nwriters {writers}".encode()).hexdigest()


def code_hash() -> str:
    """The code hash of a release: the SHA-256 of the hash of the code the chunks are made under (the model, the solver and what they read:
    :func:`trioforge.precompute.grid._code_hash`) and the hash of the code that writes the files of a trio (:func:`writer_hash`). The deploy check compares it, so a
    release whose writers have changed since is seen."""
    from trioforge.precompute import grid

    return combine_code_hashes(grid._code_hash(), writer_hash())


def _need(ok: bool, what: str) -> None:
    if not ok:
        raise ReleaseRefused(f"release.json: {what}")


def check_release_document(doc: Mapping[str, Any]) -> None:
    """Hold a ``release.json`` document to its form (the fields of :data:`RELEASE_KEYS` and nothing else, each of the right kind)."""
    _need(isinstance(doc, Mapping), "is not an object")
    _need(list(doc) == list(RELEASE_KEYS), f"must have the fields {', '.join(RELEASE_KEYS)}, in that order")
    _need(doc["format"] == FORMAT and not isinstance(doc["format"], bool), f"format must be {FORMAT}")
    try:
        check_tag(doc["release"])
    except ReleaseRefused:
        raise ReleaseRefused("release.json: release must be a tag such as data-2026-10-17") from None
    _need(_calendar(doc["catalog_date"]), "catalog_date must be a calendar date, YYYY-MM-DD")
    _need(_calendar(doc["rules_version"]), "rules_version must be a date, YYYY-MM-DD")
    _need(_calendar(doc["game_patch"]), "game_patch must be a date, YYYY-MM-DD")
    for name in ("catalog_sha256", "code_hash"):
        _need(isinstance(doc[name], str) and _SHA256.fullmatch(doc[name]) is not None, f"{name} must be 64 lower-case hexadecimal digits")
    _need(isinstance(doc["snapshot_id"], str) and _SNAPSHOT.fullmatch(doc["snapshot_id"]) is not None, "snapshot_id must be 32 lower-case hexadecimal digits")
    _need(isinstance(doc["rules"], Mapping) and all(isinstance(k, str) and isinstance(v, Mapping) for k, v in doc["rules"].items()), "rules must map a rule id to its entry")
    for name in ("solver", "build_options"):
        _need(isinstance(doc[name], Mapping), f"{name} must be an object")
    _need(type(doc["level"]) is int and 1 <= doc["level"] <= 99, "level must be a character level, 1 to 99")
    _need(type(doc["trial"]) is bool, "trial must be true or false")
    found = _PARITY_SAMPLE.fullmatch(doc["parity_sample"]) if isinstance(doc["parity_sample"], str) else None
    _need(found is not None and int(found.group(1)) < int(found.group(2)), "parity_sample must be i/n, the offset i from 0 to n-1 of the sample of the parity suite")
    trios = doc["trios"]
    _need(isinstance(trios, Mapping) and bool(trios) and all(is_trio_slug(slug) for slug in trios), "trios must map the folder of each trio (such as pal-mnk-ber) to its tiers")
    for slug, tiers in trios.items():
        ok = isinstance(tiers, list) and bool(tiers) and all(type(t) is int and 0 <= t <= 10 for t in tiers) and tiers == sorted(set(tiers))
        _need(ok, f"the tiers of {slug} must be a list of tiers, 0 to 10, ascending, each once")
    evidence = doc["evidence"]
    ok = isinstance(evidence, Mapping) and all(
        isinstance(key, str) and _ITEM_KEY.fullmatch(key) is not None and level in LEVELS for key, level in evidence.items()
    )
    _need(ok, f"evidence must map an item key (small letters, digits and hyphens) to a level of {', '.join(LEVELS)}")


def release_document(
    *, tag: str, catalog_date: str, catalog_sha256: str, rules_version: str, rules: Mapping[str, Mapping[str, Any]], code_hash: str,
    solver: Mapping[str, Any], build_options: Mapping[str, Any], level: int, game_patch: str, trios: Mapping[str, Sequence[int]],
    evidence: Mapping[str, str], snapshot_id: str, parity_sample: str, trial: bool = False,
) -> dict[str, Any]:
    """The document of ``release.json`` (see the module docstring). ``trios`` maps the folder of each trio to its tiers. :class:`ReleaseRefused` for a
    value that is not of the form :func:`check_release_document` asks."""
    doc = {
        "format": FORMAT, "release": tag, "catalog_date": catalog_date, "catalog_sha256": catalog_sha256, "rules_version": rules_version,
        "rules": {key: dict(rules[key]) for key in sorted(rules)}, "code_hash": code_hash, "solver": dict(solver), "build_options": dict(build_options),
        "level": level, "game_patch": game_patch, "trial": trial, "parity_sample": parity_sample, "trios": {slug: list(trios[slug]) for slug in sorted(trios)},
        "evidence": dict(sorted(evidence.items())), "snapshot_id": snapshot_id,
    }  # fmt: skip
    check_release_document(doc)
    return doc


def write_release_json(folder: str | os.PathLike[str], doc: Mapping[str, Any]) -> Path:
    """Write ``release.json`` into ``folder`` (all or nothing), one entry of the evidence map, the rules and the trios to a line."""
    check_release_document(doc)
    target = Path(folder)
    commit_files(target, {RELEASE_FILE: render(dict(doc), per_line=("rules", "trios", "evidence"))}, last=RELEASE_FILE)
    return target / RELEASE_FILE


def read_release_json(folder: str | os.PathLike[str]) -> dict[str, Any]:
    """Read and check the ``release.json`` of a release folder."""
    path = Path(folder) / RELEASE_FILE
    try:
        doc = load_strict(path)
    except FileNotFoundError:
        raise ReleaseRefused(f"{RELEASE_FILE} is not in {Path(folder).name}") from None
    except (OSError, JsonFileError) as error:
        raise ReleaseRefused(f"{RELEASE_FILE} cannot be read: {error}") from None
    check_release_document(doc)
    return doc


def pointer_document(release: Mapping[str, Any], asset_sha256: str) -> dict[str, Any]:
    """The pointer ``releases/<tag>.json`` of a release document (see the module docstring): the fields of :data:`POINTER_KEYS`, from the document
    itself and the SHA-256 of the asset."""
    doc = {name: (asset_sha256 if name == "asset_sha256" else release[name]) for name in POINTER_KEYS}
    check_pointer(doc)
    return doc


def check_pointer(doc: Mapping[str, Any], name: str | None = None) -> None:
    """Hold a pointer to its form; with ``name`` (the file's name without ``.json``) the tag in it must be the file's."""

    def need(ok: bool, what: str) -> None:
        if not ok:
            raise ReleaseRefused(f"the pointer {name or 'of a release'}: {what}")

    need(isinstance(doc, Mapping) and list(doc) == list(POINTER_KEYS), f"must have the fields {', '.join(POINTER_KEYS)}, in that order and no other")
    need(doc["format"] == FORMAT and not isinstance(doc["format"], bool), f"format must be {FORMAT}")
    try:
        check_tag(doc["release"])
    except ReleaseRefused:
        raise ReleaseRefused(f"the pointer {name or 'of a release'}: release must be a tag such as data-2026-10-17") from None
    need(name is None or doc["release"] == name, f"names the release {doc['release']}, which is not the tag in the name of the file")
    for field in ("asset_sha256", "catalog_sha256", "code_hash"):
        need(isinstance(doc[field], str) and _SHA256.fullmatch(doc[field]) is not None, f"{field} must be 64 lower-case hexadecimal digits")
    need(isinstance(doc["snapshot_id"], str) and _SNAPSHOT.fullmatch(doc["snapshot_id"]) is not None, "snapshot_id must be 32 lower-case hexadecimal digits")
    need(_calendar(doc["catalog_date"]) and _calendar(doc["rules_version"]), "catalog_date and rules_version must be dates, YYYY-MM-DD")
    need(isinstance(doc["solver"], Mapping) and isinstance(doc["build_options"], Mapping), "solver and build_options must be objects")


def write_pointer(path: str | os.PathLike[str], doc: Mapping[str, Any]) -> Path:
    """Write the pointer to ``path`` (all or nothing); the file must be named for the tag in it."""
    target = Path(path)
    check_pointer(doc, target.name.removesuffix(".json"))
    commit_files(target.parent, {target.name: render(dict(doc))}, last=target.name)
    return target


def read_pointer(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read and check a pointer; the tag in it must be the file's."""
    target = Path(path)
    try:
        doc = load_strict(target)
    except (OSError, JsonFileError) as error:
        raise ReleaseRefused(f"the pointer {target.name} cannot be read: {error}") from None
    check_pointer(doc, target.name.removesuffix(".json"))
    return doc


# ---- the asset ----------------------------------------------------------------------------------------------------------------------------


def pack(folder: str | os.PathLike[str], asset: str | os.PathLike[str]) -> str:
    """Pack the files under ``folder`` into the ``tar.gz`` ``asset`` and return its SHA-256. The bytes depend on the files alone: sorted flat names, plain
    files, mode 0644, owner 0, no names of owners and no dates, and a gzip header with no time. The asset is written to a temporary file and renamed, so a
    failure leaves none."""
    root, target = Path(folder), Path(asset)
    names = _walk(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode="w", format=tarfile.GNU_FORMAT) as archive:
                    for name in names:
                        info = tarfile.TarInfo(name)
                        info.size = (root / name).stat().st_size
                        info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = 0, 0o644, 0, 0, "", ""
                        with (root / name).open("rb") as handle:
                            archive.addfile(info, handle)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256_of(target)


def verify_asset(asset: str | os.PathLike[str], wanted: Mapping[str, tuple[int, str]]) -> None:
    """Hold the members of ``asset`` to ``wanted`` (the :func:`manifest` of the folder that was checked and scanned): the same names, sizes and digests,
    so that what ships is what was scanned. :class:`ReleaseRefused` names the first member that differs, is missing or is extra."""
    seen: set[str] = set()
    with tarfile.open(asset, "r:gz") as archive:
        for member in archive:
            if not member.isreg():
                raise ReleaseRefused(f"the asset has a member that is not a file: {member.name}")
            if member.name not in wanted:
                raise ReleaseRefused(f"the asset has a member that was not scanned: {member.name}")
            digest = hashlib.sha256()
            handle = archive.extractfile(member)
            assert handle is not None
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
            if (member.size, digest.hexdigest()) != tuple(wanted[member.name]):
                raise ReleaseRefused(f"the asset member {member.name} differs from the file that was scanned")
            seen.add(member.name)
    for name in sorted(set(wanted) - seen):
        raise ReleaseRefused(f"the asset lacks {name}, which was scanned")


def _safe_member(name: str) -> None:
    parts = name.split("/")
    for part in parts:
        bad = (
            part in ("", ".", "..") or "\\" in part or ":" in part or part != part.rstrip(" .")
            or any(ord(char) < 32 for char in part) or _RESERVED.fullmatch(part) is not None
        )
        if bad:
            raise ReleaseRefused(f"unsafe member name {name!r} in the asset")


def extract(asset: str | os.PathLike[str], destination: str | os.PathLike[str], *, max_member: int = MAX_MEMBER) -> int:
    """Unpack ``asset`` into the new (or empty) folder ``destination`` and return the number of files. Files only: a link, a name that could leave the
    folder (absolute, ``..``, a drive, a backslash, a device name), a name twice and a file larger than ``max_member`` bytes are refused; a failure
    removes what was written."""
    target = Path(destination)
    if target.exists() and any(target.iterdir()):
        raise ReleaseRefused(f"the folder {target.name} to unpack into is not empty")
    made = not target.exists()
    target.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()
    try:
        with tarfile.open(asset, "r:gz") as archive:
            for member in archive:
                if not member.isreg():
                    raise ReleaseRefused(f"the asset has a member that is not a file: {member.name}")
                _safe_member(member.name)
                if member.name in names:
                    raise ReleaseRefused(f"the asset has the member {member.name} twice")
                if member.size > max_member:
                    raise ReleaseRefused(f"the asset member {member.name} is larger than {max_member:,} bytes")
                names.add(member.name)
                path = target / member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                handle = archive.extractfile(member)
                assert handle is not None
                with path.open("wb") as out:
                    shutil.copyfileobj(handle, out)
    except BaseException:
        if made:
            shutil.rmtree(target, ignore_errors=True)
        raise
    return len(names)

