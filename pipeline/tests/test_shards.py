"""The CI job of the Python tests is a matrix of shards over the test files (Part Q, Q2).

The job ran the whole suite in one go, and with the tests that need Node (which CI skipped until Part L) it could not finish in the 30 minutes that the hardening test allows. The suite is now cut by test FILE
(``shards.py``: a file is in exactly one shard, a few heavy ones are placed by hand and the rest by a hash of the name), the job runs one shard in each cell of a matrix (``python -m pytest --shard I/N``), and
these tests hold the cut: the shards together cover every test file exactly once, none is empty, the option keeps exactly the files of its shard, and the workflow's matrix is the one the code has.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import shards
import yaml

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
FILES = sorted(path.name for path in TESTS.glob("test_*.py"))


def test_the_shards_together_cover_every_test_file_exactly_once_and_none_is_empty():
    assert len(FILES) > 100, "the test files were found"
    split = shards.split(FILES)
    assert sorted(split) == list(range(1, shards.SHARDS + 1))
    assert sorted(name for names in split.values() for name in names) == FILES, "every file in some shard, and in only one"
    assert all(names for names in split.values()), "no shard is empty"


def test_a_file_is_in_the_same_shard_whatever_else_is_in_the_suite():
    """The shard of a file depends on its name alone (and on the table of heavy files): adding or removing another file moves nothing."""
    alone = {name: shards.shard_of(name) for name in FILES}
    without_some = shards.split(FILES[::2])
    for index, names in without_some.items():
        assert all(alone[name] == index for name in names)
    assert shards.shard_of("test_a_file_that_does_not_exist_yet.py") == shards.shard_of("test_a_file_that_does_not_exist_yet.py")
    assert 1 <= shards.shard_of("test_a_file_that_does_not_exist_yet.py") <= shards.SHARDS


def test_the_heavy_files_are_files_that_exist_and_are_placed_in_a_shard_that_there_is():
    assert set(shards.HEAVY) <= set(FILES), "a name in HEAVY is no test file (renamed or removed?)"
    assert all(1 <= index <= shards.SHARDS and seconds > 0 for index, seconds in shards.HEAVY.values())


def test_the_heavy_files_are_spread_so_that_no_shard_has_much_more_of_their_time_than_another():
    """The seconds are those measured in a whole run (the biggest file alone, test_release_build.py, is the most of a shard: it cannot be split); the shards' shares of them are within a third of each other."""
    assert len(shards.HEAVY) >= 4 * shards.SHARDS, "there are heavy files to place: enough that each shard has some"
    seconds = [sum(took for index, took in shards.HEAVY.values() if index == shard) for shard in range(1, shards.SHARDS + 1)]
    assert all(seconds), "every shard has heavy files"
    assert max(seconds) <= 1.33 * min(seconds), seconds
    assert sum(seconds) > 2000, "the measured seconds are those of a whole run: the heavy files are most of an hour"


@pytest.mark.parametrize(("text", "expected"), [("1/4", (1, 4)), ("4/4", (4, 4)), ("5/5", (5, 5)), (" 2/3 ", (2, 3)), ("1/1", (1, 1))])
def test_the_option_is_i_over_n(text, expected):
    assert shards.parse(text) == expected


@pytest.mark.parametrize("text", ["", "4", "0/4", "5/4", "1/0", "a/4", "1/4/4", "-1/4", "1.5/4", "1 / 4x", "\u0661/\u0665", "1/\u0665", "\uff11/\uff15", "\u00b2/\u00b3"])  # (the last four: digits of other scripts, which isdigit() and int() take)
def test_anything_else_is_refused(text):
    with pytest.raises(ValueError, match="--shard"):
        shards.parse(text)


def collected(*arguments: str) -> set[str]:
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode in (0, 5), done.stdout + done.stderr  # (5: no test of this shard among the files asked for)
    return {line.split("::")[0].rsplit("/", 1)[-1] for line in done.stdout.splitlines() if "::" in line}


def test_the_option_keeps_exactly_the_files_of_its_shard_and_a_run_without_it_is_the_whole_suite():
    small = ["pipeline/tests/test_shards.py", "pipeline/tests/test_checks_dir.py", "pipeline/tests/test_rules.py", "pipeline/tests/test_formulas.py"]
    names = [Path(path).name for path in small if (ROOT / path).is_file()]
    assert len(names) >= 3
    assert collected(*small) == set(names), "no option: every file"
    seen: set[str] = set()
    for index in range(1, shards.SHARDS + 1):
        here = collected("--shard", f"{index}/{shards.SHARDS}", *small)
        assert here == {name for name in names if shards.shard_of(name) == index}, index
        assert not seen & here
        seen |= here
    assert seen == set(names), "the shards together are the files"


def test_a_shard_that_is_not_i_over_n_is_a_usage_error_and_runs_nothing():
    done = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider", "--shard", "9/4", "pipeline/tests/test_shards.py"], cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 4 and "--shard" in done.stderr


# ---- the workflow runs the shards --------------------------------------------------------------------------------------------------------------------------


def workflow():
    return yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8"))


def test_the_python_job_is_a_matrix_of_exactly_the_shards_the_code_has_and_runs_one_in_each_cell():
    job = workflow()["jobs"]["python"]
    matrix = job["strategy"]["matrix"]["shard"]
    assert matrix == [f"{index}/{shards.SHARDS}" for index in range(1, shards.SHARDS + 1)], "the matrix names every shard of SHARDS, once"
    assert job["strategy"].get("fail-fast") is False, "one shard that fails does not cancel the others: a run shows every failure"
    steps = [step for step in job["steps"] if isinstance(step, dict)]
    run = next(step for step in steps if "pytest" in str(step.get("run", "")))
    assert run["run"] == 'python -m pytest --shard "$SHARD"'
    assert run["env"]["SHARD"] == "${{ matrix.shard }}", "the cell's shard reaches the command through the environment (a run script has no expression: the hardening test)"
    assert run["env"]["TRIOFORGE_REQUIRE_NODE"] == "1", "each shard needs Node set up the same, and requires it"
    assert job["timeout-minutes"] <= 30
    assert [step["uses"].split("@")[0] for step in steps if "uses" in step] == ["actions/checkout", "actions/setup-node", "actions/setup-python"], "the set-up is the same in each cell"
