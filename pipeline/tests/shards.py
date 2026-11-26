"""The shards of the suite: which test files the CI job of each shard runs. This module holds no tests (``test_shards.py`` does).

The suite is slow (the whole of it is an hour on the maintainer's computer: solver runs, site builds, the release checks), so CI runs it as ``SHARDS`` jobs of a matrix, each given a share of the test FILES
(``python -m pytest --shard I/N``, see ``conftest.py``): a file is never split, because its module-scoped fixtures (a site build, a precompute) are made once for the file and cost most of its time.

The shard of a file is stable: a few heavy files are placed by hand in ``HEAVY`` (so that no shard is much slower than another), and every other file goes by a hash of its name, so that a new test
file lands in a shard without anyone choosing it, and no file is ever in two or in none. ``test_shards.py`` holds that the shards together cover every test file exactly once, and that the workflow lists
the same number of shards as ``SHARDS``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

__all__ = ["HEAVY", "SHARDS", "parse", "shard_of", "split"]

#: How many shards the CI job has (the workflow's matrix names the same ``1/SHARDS`` ... ``SHARDS/SHARDS``).
SHARDS = 5

#: The files that take most of the time, put in a shard by hand: file name -> (shard, seconds that the file took in a whole run on the maintainer's computer, which was busy with other work at the time).
#: Placed longest first, each into the shard that had the least so far, so that the shards are about equal (heavy seconds per shard: 693, 583, 582, 581 and 547; with the files that go by the hash, a
#: shard is about 13 to 16 minutes there). Only for ``SHARDS`` shards: any other count goes by the hash alone. A new heavy file goes in by hand; until then it is in a shard by its hash, as any other.
HEAVY: dict[str, tuple[int, int]] = {
    "test_release_build.py": (1, 693),
    "test_kit_checks_cli.py": (2, 45),
    "test_milp_owned.py": (2, 48),
    "test_precompute.py": (2, 280),
    "test_site_engine_fixture.py": (2, 91),
    "test_site_itemicon.py": (2, 119),
    "test_export_browser.py": (3, 104),
    "test_milp_bruteforce.py": (3, 64),
    "test_precompute_engine.py": (3, 48),
    "test_prune.py": (3, 125),
    "test_site_data.py": (3, 42),
    "test_site_integration.py": (3, 199),
    "test_bench.py": (4, 43),
    "test_export_fixtures.py": (4, 189),
    "test_privacy_git.py": (4, 49),
    "test_prune_owned.py": (4, 65),
    "test_results_diff.py": (4, 94),
    "test_site_build.py": (4, 141),
    "test_catalog.py": (5, 80),
    "test_release_checks.py": (5, 145),
    "test_site_icons.py": (5, 108),
    "test_site_item_pages.py": (5, 47),
    "test_upgrade.py": (5, 167),
}


def shard_of(name: str, count: int = SHARDS) -> int:
    """The shard (1 to ``count``) that the test file called ``name`` (its file name, no folder) belongs to."""
    if count == SHARDS and name in HEAVY:
        return HEAVY[name][0]
    return int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big") % count + 1


def split(names: Iterable[str], count: int = SHARDS) -> dict[int, list[str]]:
    """The test files ``names`` by shard: every shard 1 to ``count`` is a key, every name is in exactly one of them, each list in sorted order."""
    found: dict[int, list[str]] = {index: [] for index in range(1, count + 1)}
    for name in sorted(names):
        found[shard_of(name, count)].append(name)
    return found


def parse(text: str) -> tuple[int, int]:
    """``"2/4"`` as ``(2, 4)``: the shard and how many there are. Raises ``ValueError`` for anything else (a shard of 1 to N, N at least 1)."""
    found = re.fullmatch(r"([0-9]+)/([0-9]+)", text.strip())  # (the ASCII digits only: isdigit() and int() take the digits of other scripts)
    if found is None:
        raise ValueError(f"--shard is I/N, such as 2/4 (it is {text!r})")
    index, count = int(found.group(1)), int(found.group(2))
    if count < 1 or not 1 <= index <= count:
        raise ValueError(f"--shard I/N needs N of at least 1 and I from 1 to N (it is {text!r})")
    return index, count
