"""No file of the repository and no commit message holds a count that the maintainer's private seen flags decide.

The item table of a real build has the flags merged into its evidence levels: the number of strict items is the number of items the flags make strict, and the number of
pages (the strict and wiki items) is the public catalog's wiki items and the items a sighting rescued from hidden or disputed. A number like that is the flags in another form, so it
is written nowhere: not in a test, a fixture, DECISIONS, the changelog or a commit message. The name scan of ``test_site_fixture_items.py`` does not look at numbers, so this does.

The figures themselves are worked out here, at run time, from the real results of this computer (``$TRIOFORGE_RESULTS``, else ``build/results``) and compared with the public catalog
(``derived/catalog.json``) alone: a count is one of them when the flags changed it. They are never written down, and a failure names the files that hold one and not the figure.
Where there are no real results (CI, another clone) the scan of the repository is skipped, and the scan itself is held to small made-up texts.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from collections.abc import Collection
from pathlib import Path

import pytest

from trioforge import rules as rules_module
from trioforge.export import browser

REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / "derived" / "catalog.json"
RULES = REPO / "rules" / "rules.json"
#: the files that tell what the item pages are and how they are tested: where a count of the real results could be written
SCANNED = (
    "docs/DECISIONS.md",
    "docs/CHANGELOG.md",
    "pipeline/tests/test_site_build.py",
    "pipeline/tests/test_site_counts.py",
    "pipeline/tests/test_site_files.py",
    "pipeline/tests/test_site_fixture_items.py",
    "pipeline/tests/test_site_item_pages.py",
    "pipeline/tests/test_site_items.py",
    "tests-e2e/item.spec.mjs",
    "tests-js/trio.test.mjs",
)
LEAST = 100  # a smaller number is in every file


def real_results() -> Path | None:
    """The folder of real results of this computer (``$TRIOFORGE_RESULTS``, else ``build/results``), or None: only the maintainer's computer has one."""
    given = os.environ.get("TRIOFORGE_RESULTS")
    path = REPO / given if given else REPO / "build" / "results"
    return path if (path / "items.json").is_file() else None


def levels(table: dict) -> Counter:
    return Counter(record["evidence"]["level"] for record in table["items"])


def counts_the_flags_decide(results: Path) -> set[int]:
    """The counts of the item table of ``results`` that the seen flags decide: the number of items at an evidence level where it is not the number the public catalog alone gives, and
    the number of pages (strict and wiki items) where it is not the public catalog's. Only counts of ``LEAST`` and more."""
    real = json.loads((results / "items.json").read_text(encoding="utf-8"))
    public = browser.items(json.loads(CATALOG.read_text(encoding="utf-8")), rules_module.load(RULES))
    mine, theirs = levels(real), levels(public)
    figures = {mine[level] for level in mine if mine[level] != theirs[level]}
    pages = lambda count: count["strict"] + count["wiki"]  # noqa: E731
    if pages(mine) != pages(theirs):
        figures.add(pages(mine))
    return {figure for figure in figures if figure >= LEAST}


def figures_in(text: str, figures: Collection[int]) -> set[int]:
    """Which of ``figures`` the text writes, with or without its thousands separator, as a number of its own (not inside a longer number, a decimal or a word of digits)."""
    found = set()
    for figure in figures:
        plain, grouped = str(figure), f"{figure:,}"
        if re.search(rf"(?<![0-9.,])(?:{plain}|{re.escape(grouped)})(?![0-9])", text):
            found.add(figure)
    return found


def git_messages() -> str:
    """The messages of the last commits of this checkout (empty where git cannot say)."""
    try:
        done = subprocess.run(
            ["git", "log", "-n", "300", "--format=%B"], cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout


# ---- the scan itself: made-up figures and texts ------------------------------------------------------------------------------------------------


def test_the_scan_finds_a_figure_with_or_without_its_separator_and_leaves_look_alikes_alone():
    figures = {8642, 357}  # (made up: not a count of any results)
    assert figures_in("it has 8,642 pages, 357 of them strict; 8642 once more", figures) == figures
    assert figures_in("18,642 and 3570 and 0.357 and 1.8642 and w86420 and 86,420 and 8642x", figures) == {8642}  # (the last is a figure next to a letter: it still counts)
    assert figures_in("(357), 357. and “8,642”", figures) == figures
    assert figures_in("", figures) == set() and figures_in("8642", set()) == set()


def test_the_counts_the_flags_decide_are_the_ones_the_public_catalog_alone_does_not_give(tmp_path):
    public = browser.items(json.loads(CATALOG.read_text(encoding="utf-8")), rules_module.load(RULES))
    kept = Counter(levels(public))
    assert kept["wiki"] > LEAST and kept["strict"] == 0  # (the public catalog has no strict item: that level comes from the flags alone)
    # a table in which two hidden items were rescued by a sighting: the wiki items are the public ones, the rescued are strict
    table = json.loads(json.dumps(public))
    rescued = [record for record in table["items"] if record["evidence"]["level"] == "hidden"][:2]
    for record in rescued:
        record["evidence"] = {"level": "strict", "codes": record["evidence"].get("codes", [])}
        record.pop("owned_only", None)
    (tmp_path / "items.json").write_text(json.dumps(table), encoding="utf-8")
    mine = levels(table)
    assert mine["strict"] == 2 and mine["hidden"] == kept["hidden"] - 2 and mine["wiki"] == kept["wiki"]
    # the hidden count and the number of pages are not the public ones; the strict count is too, but a count so small is in every file; the wiki and the disputed counts are the public ones
    assert counts_the_flags_decide(tmp_path) == {kept["hidden"] - 2, kept["wiki"] + 2}


# ---- the repository and its history, against the real results of this computer -------------------------------------------------------------


def test_no_file_and_no_commit_message_holds_a_count_that_the_private_seen_flags_decide():
    results = real_results()
    if results is None:
        pytest.skip("there are no real results here ($TRIOFORGE_RESULTS, build/results): the counts the seen flags decide are worked out from them")
    figures = counts_the_flags_decide(results)
    if not figures:
        pytest.skip("the real results carry no count that the seen flags decide")
    holders = [name for name in SCANNED if figures_in((REPO / name).read_text(encoding="utf-8"), figures)]
    if figures_in(git_messages(), figures):
        holders.append("a commit message")
    assert not holders, f"these hold a count that the private seen flags decide (the figure is not printed here): {holders}"
