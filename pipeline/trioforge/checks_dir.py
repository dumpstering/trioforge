"""The one folder, outside every worktree, where the scheduled checks leave their stamps, logs and reports, and from which the release build reads the stamps.

The three checks (``scripts/sources_check.py``, ``scripts/pins_check.py`` and ``scripts/smoke_live.mjs``) run from the Task Scheduler in one checkout, the main one. A
release build runs from a worktree of its own (``CONTRIBUTING.md``), so a stamp in the ``build/`` folder of the first is never seen by the second: it would warn "no
stamp" for every release, whatever the checks had done. The folder is therefore a place of the user's own, the same for every checkout:

* ``$TRIOFORGE_CHECKS_DIR`` if it is set. An empty or blank value counts as unset. It must be an absolute path -- a relative one would be a different folder for each working
  folder -- by one rule in Python and in Node: on Windows a drive (``C:\\x``, ``C:/x``) or a UNC path (``\\\\server\\share\\x``), elsewhere a path that starts with ``/``. It must not lie
  inside a git work tree (a ``.git`` directory, or the ``.git`` file of a linked worktree, in the folder or above it): a stamp there would be a file of that checkout. Anything
  else is refused (:class:`ValueError`);
* else ``~/.local/state/trioforge/checks``, on Windows too. It is *not* ``%LOCALAPPDATA%``: a program that runs from the Claude app writes there to a private copy that the Task
  Scheduler never sees. (The default is not held to the work-tree rule, since the home of a user can itself be a repository.)

Standard library only: the checks import this file by loading its path, and the smoke check (Node) works the same folder out by the same rules.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

__all__ = ["ENVIRONMENT_VARIABLE", "checks_dir", "in_a_work_tree", "is_absolute"]

ENVIRONMENT_VARIABLE = "TRIOFORGE_CHECKS_DIR"

_WINDOWS_ABSOLUTE = re.compile(r"[A-Za-z]:[\\/]|[\\/]{2}[^\\/]+[\\/]+[^\\/]")  # a drive and a separator, or \\server\share


def is_absolute(text: str, platform: str | None = None) -> bool:
    """Whether ``text`` is an absolute path by the one rule of the checks (the same in Node): on Windows (``win32``) a drive and a separator, or a UNC path ``\\\\server\\share``;
    elsewhere a path that starts with ``/``. A path that only has a root (``\\x``) or only a drive (``C:x``) is relative to something, and is not absolute. No file is looked at."""
    kind = sys.platform if platform is None else platform
    if kind == "win32":
        return _WINDOWS_ABSOLUTE.match(text) is not None
    return text.startswith("/")


def in_a_work_tree(folder: Path) -> bool:
    """Whether ``folder`` is in a git work tree: it or a folder above it holds a ``.git`` (a directory, or the file of a linked worktree). The folder need not be there yet."""
    for candidate in (folder, *folder.parents):
        if os.path.lexists(candidate / ".git"):
            return True
    return False


def checks_dir(environ: Mapping[str, str] | None = None, *, platform: str | None = None, home: Path | None = None) -> Path:
    """The folder of the stamps, logs and reports of the scheduled checks (see the module's description).

    ``environ``, ``platform`` and ``home`` default to those of the process; a test gives its own. Raises :class:`ValueError` if ``$TRIOFORGE_CHECKS_DIR`` is set to a path that is
    not absolute or is in a git work tree.
    """
    env = os.environ if environ is None else environ
    kind = sys.platform if platform is None else platform
    given = (env.get(ENVIRONMENT_VARIABLE) or "").strip()
    if given:
        if not is_absolute(given, kind):
            raise ValueError(
                f"{ENVIRONMENT_VARIABLE} must be an absolute path (it is {given!r}; on Windows a drive or a UNC path, elsewhere a path that starts with /): "
                "the checks and the release build run in different folders, and must find the same one"
            )
        folder = Path(given)
        if in_a_work_tree(folder):
            raise ValueError(f"{ENVIRONMENT_VARIABLE} must not be inside a git work tree ({given!r}): a stamp there would be a file of that checkout")
        return folder
    profile = Path.home() if home is None else home
    return profile / ".local" / "state" / "trioforge" / "checks"
