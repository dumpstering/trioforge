"""Results made before the builds, or with other rules.

An earlier release had a Balanced build that blended the others (:data:`trioforge.model.roles.REMOVED_ROLES`), and its results were solved under other rules (an
earlier ``version`` of ``rules/rules.json``). Results of either kind are not read half-way: a reader says so and stops, and a run of the precompute refuses to
resume into them. A folder is old when

* it holds the Balanced build (a chunk file or a runner-up file named for it, a shard or ``robust.json`` that lists it, a ``defaults.json`` whose view is it), or
* a file of it records a ``rules_version`` other than the rules file's, or none (:func:`other_rules_files`). This also catches a narrowed old run that never listed Balanced (only
  the Tank's shards), and a folder that holds only a ``runnerups/index.json``, an ``engine-l*.json`` or an ``exalt.json`` of the earlier code. A file that a writer makes records
  its version in the bytes that are read for it: one that records none, a null or a version after those bytes is not a file of these rules, as the site's reader and the checker say.

This module knows how to tell them (a name, a header and a view, never the rest of a file), and is light on purpose: the site generator and the precompute both import it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from trioforge.model.roles import REMOVED_ROLES

__all__ = ["current_rules_version", "old_role_files", "other_rules_files", "refusal", "stale"]

_SHARDS = tuple(f"{evidence}-{buffs}.json" for evidence in ("strict", "wiki") for buffs in ("own", "group"))
_RUNNERUPS = "runnerups"
#: the files of a trio's folder that the writers make, each with the rules version in its header (a file by another name is none of theirs: it is asked for no version, and refused
#: only if it records another)
_WRITTEN = (*_SHARDS, "defaults.json", "robust.json", "exalt.json")
_WRITTEN_PREFIX = "engine-l"
_HEADER = 16384  # bytes: every writer puts ``rules_version`` in the header of a file, before its tables
_RECORDED = re.compile(r'"rules_version"\s*:\s*"([^"\\]*)"')


def current_rules_version(root: str | Path | None = None) -> str:
    """The ``version`` of the rules file under ``root`` (a tables root: the repository by default)."""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    return str(json.loads((base / "rules" / "rules.json").read_text(encoding="utf-8"))["version"])


def old_role_files(trio_dir: Path) -> list[str]:
    """The files of a trio's folder that were made with a build that no longer exists (:data:`trioforge.model.roles.REMOVED_ROLES`: Balanced), as names relative to the
    folder, sorted: a chunk file or a runner-up file named for it, a runner-up file of it, a shard or ``robust.json`` that lists it among its roles and a ``defaults.json``
    whose view is it. Empty for a folder that is new or made with the builds of this release."""
    found: set[str] = set()
    for role in REMOVED_ROLES:
        for pattern in (f"chunks/s-*-{role}-*.json", f"chunks/r-{role}-t*.json", f"{_RUNNERUPS}/{role}.json"):
            found.update(path.relative_to(trio_dir).as_posix() for path in trio_dir.glob(pattern))
    for name in (*_SHARDS, "defaults.json", "robust.json"):
        path = trio_dir / name
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # (a file that cannot be read is for the reader of it to refuse, with its own words)
        if not isinstance(doc, dict):
            continue
        roles = doc.get("roles") if isinstance(doc.get("roles"), (list, dict)) else []
        view = doc.get("view") if isinstance(doc.get("view"), dict) else {}
        if REMOVED_ROLES & {*roles, view.get("role")}:
            found.add(name)
    return sorted(found)


def _is_written(name: str) -> bool:
    """Whether ``name`` (relative to the trio's folder) is a file that the writers of a results folder make: a shard, ``defaults.json``, ``robust.json``, ``exalt.json``, the browser
    bundle ``engine-l<level>.json`` or a file of the ``runnerups`` folder."""
    return name in _WRITTEN or name.startswith(f"{_RUNNERUPS}/") or (name.startswith(_WRITTEN_PREFIX) and "/" not in name)


def other_rules_files(trio_dir: Path, rules_version: str) -> list[tuple[str, str | None]]:
    """``(file, the rules version it records)`` for each file of the folder (the trio's own files and its ``runnerups`` folder; not the chunks) that is not of ``rules_version``,
    sorted by name: one that records another, or (``None``) a file that a writer makes (:func:`_is_written`) and that records none in the bytes read for it (no field, a field that
    is not a text, or a field after the header). A file that cannot be read is no finding here: the reader of it says what is wrong with it."""
    found: list[tuple[str, str | None]] = []
    for path in sorted([*trio_dir.glob("*.json"), *trio_dir.glob(f"{_RUNNERUPS}/*.json")]):
        name = path.relative_to(trio_dir).as_posix()
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                head = handle.read(_HEADER)
        except OSError:
            continue
        match = _RECORDED.search(head)
        if match is None:
            if _is_written(name):
                found.append((name, None))
        elif match.group(1) != rules_version:
            found.append((name, match.group(1)))
    return found


def refusal(slug: str, files: list[str], other: list[tuple[str, str | None]] | None = None, rules_version: str | None = None) -> str:
    """The sentence that says why a folder of results is refused: ``files`` are those of :func:`old_role_files`, ``other`` those of :func:`other_rules_files`
    (``rules_version`` is the rules file's)."""
    parts = []
    if files:
        shown = ", ".join(files[:3]) + (", ..." if len(files) > 3 else "")
        parts.append(f"these results were made with the Balanced build of an earlier release ({shown}), which no longer exists")
    if other:
        shown = ", ".join(f"{name} records " + ("no rules_version" if version is None else f"rules_version {version}") for name, version in other[:3]) + (", ..." if len(other) > 3 else "")
        parts.append(f"these results were made with other rules ({shown}; this is rules version {rules_version})")
    return f"{slug}: {'; '.join(parts)}; run the precompute again into a new results folder"


def stale(slug: str, trio_dir: Path, rules_version: str | None = None) -> str | None:
    """The refusal of a folder made with the Balanced build or with rules other than ``rules_version`` (the checkout's by default), or None for a folder that is neither. The one
    test that the precompute's resume, the release run and the site's reader all make."""
    version = current_rules_version() if rules_version is None else rules_version
    files, other = old_role_files(trio_dir), other_rules_files(trio_dir, version)
    return refusal(slug, files, other, version) if files or other else None
