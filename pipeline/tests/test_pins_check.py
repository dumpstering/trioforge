"""Tests for ``scripts/pins_check.py``, the monthly check of the pins that the Task Scheduler of the maintainer's computer runs.

It reads what is pinned (the actions of ``.github/workflows`` by commit, ``requirements.txt``, ``package.json``, and the series of Node and Python the workflows
name), asks the documented APIs of GitHub, PyPI and npm for newer versions, and writes a report. A newer version counts only when it is at least 14 days old, by its
release date. It never changes a pin. Nothing here touches the network: the answers are recorded in ``fixtures/checks/pins`` (invented packages, actions and dates, in
the shape of the real answers), and a fake clock stands in for time.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest
from checks_helpers import REPO, USER_AGENT, FakeTime, FakeTransport, reply

import checks_common as common
import pins_check as pc
from trioforge.precompute import release

FIXTURES = REPO / "fixtures" / "checks" / "pins"
FIXTURE_REPO = FIXTURES / "repo"
SCRIPT = REPO / "scripts" / "pins_check.py"
NOW = datetime.datetime(2026, 10, 18, 10, 0, 3, tzinfo=datetime.timezone.utc)
LOCAL = {"python": "3.12.7", "node": "24.14.0"}
REPORT = "pins-check-2026-10-18T100003Z.md"  # (the report of a run is named for the UTC time it began: NOW)
DAY = datetime.timedelta(days=1)

SHA_PINNED, SHA_TWO, SHA_THREE = "1" * 40, "2" * 40, "3" * 40
SHA_A, SHA_B = "a" * 40, "b" * 40

LATEST = "https://api.github.com/repos/{repo}/releases?per_page=100"  # (the list of the releases of a repository, from which the highest final one is taken)
COMMIT = "https://api.github.com/repos/{repo}/commits/{tag}"
PYPI = "https://pypi.org/pypi/{name}/json"
NODE = "https://api.github.com/repos/nodejs/node/releases?per_page=100"
PYTHON = "https://api.github.com/repos/actions/python-versions/releases?per_page=100"


def utc(text: str) -> datetime.datetime:
    return common.parse_utc(text)


# ---- the network of a run: the recorded answers, with any of them replaced --------------------------------------------------------------------------------


class Net:
    """The recorded answers of ``fixtures/checks/pins``. ``replace`` maps a full address to another answer, or to an exception to raise."""

    def __init__(self, replace: dict | None = None) -> None:
        self.replay = common.ReplayTransport.from_directory(FIXTURES)
        self.replace = dict(replace or {})

    def __call__(self, url, headers):
        if url in self.replace:
            answer = self.replace[url]
            if isinstance(answer, BaseException):
                raise answer
            return answer
        return self.replay(url, headers)


def run(tmp_path, *extra, net=None, now=NOW, root=FIXTURE_REPO, local=LOCAL):
    """One run of the command in this process, on the recorded answers (or ``net``), with a clock that only moves when the run sleeps."""
    fake_time = FakeTime()
    transport = FakeTransport(fake_time, net or Net())
    out = tmp_path / "checks"
    argv = ["--root", str(root), "--out", str(out), *extra]
    before = {path.name for path in out.glob("*.md")}
    code = pc.main(argv, transport=transport, clock=fake_time.clock, sleep=fake_time.sleep, now=lambda: now, local_versions=local)
    made = sorted({path.name for path in out.glob("*.md")} - before)  # (a run never replaces a report: the one it wrote is the one that is new)
    return SimpleNamespace(code=code, transport=transport, time=fake_time, out=out, report_name=made[0] if made else REPORT)


def report(result, name: str | None = None) -> str:
    """The report that this run wrote, or the one named."""
    return (result.out / (name or getattr(result, "report_name", REPORT))).read_text(encoding="utf-8")


def summary(text: str) -> str:
    (line,) = [line for line in text.splitlines() if line.startswith("Summary: ")]
    return line.removeprefix("Summary: ").removesuffix(".")


def make_root(tmp_path: Path, workflow: str = "", requirements: str = "", package: dict | None = None) -> Path:
    """A repository with only what a test puts in it."""
    root = tmp_path / "repo"
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows" / "test.yml").write_text(workflow, encoding="utf-8")
    (root / "requirements.txt").write_text(requirements, encoding="utf-8")
    (root / "package.json").write_text(json.dumps(package or {"name": "x"}), encoding="utf-8")
    return root


def action_root(tmp_path: Path, uses: str) -> Path:
    return make_root(tmp_path, f"jobs:\n  a:\n    steps:\n      - uses: {uses}\n")


def release_answer(tag: str, published: str, **more) -> tuple:
    return reply(200, {"tag_name": tag, "name": tag, "published_at": published, "prerelease": False, "draft": False, **more})


def commit_answer(sha: str) -> tuple:
    return reply(200, {"sha": sha, "commit": {"committer": {"date": "2026-01-01T00:00:00Z"}}})


# ---- the log: a trace of every run, for a task that has no window ---------------------------------------------------------------------------------------------


def log_lines(folder) -> list[str]:
    return (folder / "pins-check.log").read_text(encoding="utf-8").splitlines()


def only_the_log(folder) -> bool:
    """A refused run leaves no report and no stamp: the one thing in its folder is the line of its log."""
    return sorted(path.name for path in folder.iterdir()) == ["pins-check.log"]


def test_a_finished_run_adds_one_line_to_the_log_with_its_counts_and_the_name_of_its_report(tmp_path):
    result = run(tmp_path)
    (line,) = log_lines(result.out)
    assert line.startswith("2026-10-18T10:00:03Z ok ") and summary(report(result)) in line
    assert re.search(r"; report pins-check-[0-9T:Z-]+\.md$", line)
    run(tmp_path, now=NOW + DAY)
    assert len(log_lines(result.out)) == 2


def test_a_refused_run_leaves_a_refused_line_and_no_stamp(tmp_path):
    result = run(tmp_path, root=tmp_path / "no-such-repository")
    assert result.code == 2
    (line,) = log_lines(result.out)
    assert line.startswith("2026-10-18T10:00:03Z refused nothing to check under ")
    assert not (result.out / "pins-check.last-run").exists()
    bad = run(tmp_path, "--contact", "ftp://nowhere.invalid/")
    assert bad.code == 2 and " refused --contact: " in log_lines(bad.out)[-1]


def test_a_run_that_crashed_leaves_an_error_line_and_an_interrupted_one_says_so(tmp_path):
    url = PYPI.format(name="examplelib")
    crashed = run(tmp_path, net=Net({url: RuntimeError("boom")}))
    assert crashed.code == 2
    assert log_lines(crashed.out)[-1] == "2026-10-18T10:00:03Z error an unexpected fault (RuntimeError); run the check by hand to see what it was"
    interrupted = run(tmp_path, net=Net({url: KeyboardInterrupt()}))
    assert interrupted.code == 130
    assert log_lines(interrupted.out)[-1] == "2026-10-18T10:00:03Z interrupted interrupted"
    assert not (crashed.out / "pins-check.last-run").exists()


def test_the_log_of_a_crash_never_holds_the_message_of_the_fault_which_can_hold_a_path_of_this_computer(tmp_path, capsys):
    result = run(tmp_path, net=Net({PYPI.format(name="examplelib"): RuntimeError(f"cannot open {tmp_path / 'private' / 'file.txt'}")}))
    assert result.code == 2
    (line,) = log_lines(result.out)
    assert str(tmp_path) not in line and "private" not in line and line.endswith(" error an unexpected fault (RuntimeError); run the check by hand to see what it was")
    assert "cannot open" in capsys.readouterr().err


def test_a_refused_run_names_the_folder_it_could_not_read_by_its_name_and_not_by_its_path_in_the_log_or_on_the_screen(tmp_path, capsys):
    result = run(tmp_path, root=tmp_path / "no-such-repository")
    (line,) = log_lines(result.out)
    err = capsys.readouterr().err
    assert str(tmp_path) not in line and str(tmp_path) not in err
    assert line.endswith(" refused nothing to check under no-such-repository: there is no .github/workflows, requirements.txt or package.json")


def test_a_command_line_that_is_wrong_leaves_a_refused_line_in_the_log_of_the_checks_folder(tmp_path):
    folder = Path(os.environ["TRIOFORGE_CHECKS_DIR"])
    with pytest.raises(SystemExit) as stopped:
        pc.main(["--no-such-option"], now=lambda: NOW)
    assert stopped.value.code == 2
    (line,) = log_lines(folder)
    assert line.startswith("2026-10-18T10:00:03Z refused ") and "--no-such-option" in line


def test_the_log_of_a_run_keeps_the_last_200_lines_and_a_log_that_cannot_be_written_changes_nothing(tmp_path):
    out = tmp_path / "checks"
    out.mkdir()
    (out / "pins-check.log").write_text("".join(f"2026-01-01T00:00:00Z ok old {n}\n" for n in range(250)), encoding="utf-8")
    lines = log_lines(run(tmp_path).out)
    assert len(lines) == 200 and lines[0].endswith("old 51") and lines[-1].startswith("2026-10-18T10:00:03Z ok ")
    (tmp_path / "other" / "checks" / "pins-check.log").mkdir(parents=True)
    result = run(tmp_path / "other")
    assert result.code == 0 and (result.out / "pins-check.last-run").is_file()


# ---- what is pinned: the workflows -----------------------------------------------------------------------------------------------------------------------

WORKFLOW = """\
name: test
jobs:
  build:
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"   #v7.0.0 and a remark
        with:
          python-version: "3.12"
      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1
        with:
          node-version: 24
      - uses: owner-x/repo-y/sub/dir@4444444444444444444444444444444444444444 # v1.2
      - uses: ./local
      - uses: ../elsewhere
      - uses: docker://alpine:3.20
      - uses: actions/cache@v4
      - uses: actions/other@main # a branch
      - run: echo "uses: not/this@1111111111111111111111111111111111111111"
"""


def test_actions_pinned_to_a_commit_are_read_with_the_tag_in_their_comment():
    workflow = pc.parse_workflow(WORKFLOW)
    found = {pin.name: (pin.sha, pin.tag) for pin in workflow.actions}
    assert found == {
        "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
        "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
        "actions/setup-node": ("949feb2413d6458794dcd2491c4babbbce0c15c1", None),
        "owner-x/repo-y/sub/dir": ("4" * 40, "v1.2"),
    }
    sub = [pin for pin in workflow.actions if pin.path][0]
    assert (sub.repo, sub.path) == ("owner-x/repo-y", "sub/dir")


def test_an_action_that_is_not_pinned_to_a_commit_is_listed_and_a_local_or_docker_one_is_left_out():
    workflow = pc.parse_workflow(WORKFLOW)
    assert workflow.unpinned == ["actions/cache@v4", "actions/other@main"]


def test_the_same_pin_in_several_places_is_one_pin():
    text = "steps:\n" + "".join(f"  - uses: a/b@{SHA_A} # v1.0.0\n" for _ in range(3)) + f"  - uses: a/b@{SHA_B} # v1.1.0\n"
    assert [(pin.sha, pin.tag) for pin in pc.parse_workflow(text).actions] == [(SHA_A, "v1.0.0"), (SHA_B, "v1.1.0")]


def test_the_series_of_node_and_python_are_read_from_the_workflows():
    assert pc.parse_workflow(WORKFLOW).runtimes == {"python": ["3.12"], "node": ["24"]}
    for text, expected in (
        ('node-version: "24.x"', {"node": ["24"]}),
        ("python-version: '3.13'", {"python": ["3.13"]}),
        ("node-version: ${{ matrix.node }}", {}),  # (not a series that can be read: it is said, in `unreadable`)
        ("node-version: lts/*", {}),
        ("      python-version: 3.12.5 # a patch", {"python": ["3.12.5"]}),
    ):
        assert pc.parse_workflow(text).runtimes == expected, text


def parsed(text: str):
    return pc.parse_workflow(text)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("node-version-file: .nvmrc", [("node", ".nvmrc")]),
        ("      python-version-file: 'pyproject.toml'", [("python", "pyproject.toml")]),
        ('      - node-version-file: "package.json" # the engines', [("node", "package.json")]),
        ("node-version-file: .nvmrc\npython-version-file: .python-version\nnode-version-file: .nvmrc", [("node", ".nvmrc"), ("python", ".python-version")]),
    ],
)
def test_a_version_that_a_workflow_reads_from_a_file_is_kept_as_such_and_not_dropped_without_a_word(text, expected):
    workflow = parsed(text)
    assert workflow.version_files == expected and workflow.runtimes == {} and workflow.unreadable == []


def test_a_version_in_the_text_and_a_version_in_a_file_are_both_kept():
    workflow = parsed("node-version: 22\nnode-version-file: .nvmrc\n")
    assert workflow.runtimes == {"node": ["22"]} and workflow.version_files == [("node", ".nvmrc")]


def test_every_series_a_workflow_names_is_kept_and_not_only_the_first():
    text = (
        "steps:\n"
        '  - uses: setup\n    with:\n      python-version: "3.11"\n'
        '  - uses: setup\n    with:\n      python-version: "3.12"\n'
        '  - uses: setup\n    with:\n      python-version: "3.12"\n'  # (the same series again is one)
        "  - uses: setup\n    with:\n      node-version: 22\n"
        "  - uses: setup\n    with:\n      node-version: 24.x\n"
    )
    assert parsed(text).runtimes == {"python": ["3.11", "3.12"], "node": ["22", "24"]}


@pytest.mark.parametrize(
    "text, expected",
    [
        ('python-version: ["3.11", "3.12"]', ["3.11", "3.12"]),
        ("python-version: [3.11, '3.12', 3.13.x]", ["3.11", "3.12", "3.13"]),
        ("python-version:\n  - '3.11'\n  - 3.12\n", ["3.11", "3.12"]),
        ("python-version:\n- 3.11\n- 3.12 # the one in use\n", ["3.11", "3.12"]),
        ("      - python-version: 3.11\n      - python-version: 3.12\n", ["3.11", "3.12"]),  # (the entries of a matrix include)
    ],
)
def test_the_series_of_a_matrix_are_read_when_it_is_written_as_a_list(text, expected):
    workflow = parsed(text)
    assert workflow.runtimes == {"python": expected} and workflow.unreadable == []


@pytest.mark.parametrize("value", ["${{ matrix.node }}", "lts/*", "latest", "$NODE", "${{ env.VERSION }}", "[${{ matrix.a }}, 22]", "~22", ">=20"])
def test_a_series_that_cannot_be_read_is_said_and_not_dropped_without_a_word(value):
    workflow = parsed(f"steps:\n  - uses: setup\n    with:\n      node-version: {value}\n")
    assert workflow.unreadable and any(name == "node" for name, _ in workflow.unreadable)
    assert all(isinstance(raw, str) for _, raw in workflow.unreadable)


def test_a_series_that_can_be_read_next_to_one_that_cannot_is_still_read():
    text = "node-version: 22\nnode-version: ${{ matrix.node }}\npython-version: 3.12\n"
    workflow = parsed(text)
    assert workflow.runtimes == {"node": ["22"], "python": ["3.12"]} and workflow.unreadable == [("node", "${{ matrix.node }}")]


def test_a_workflow_with_no_pin_has_nothing_in_it():
    workflow = pc.parse_workflow("name: x\njobs: {}\n")
    assert workflow.actions == [] and workflow.unpinned == [] and workflow.runtimes == {} and workflow.unreadable == []


# ---- what is pinned: requirements.txt and package.json ----------------------------------------------------------------------------------------------------


def test_exact_python_pins_are_read_and_the_rest_is_not_checked():
    text = """\
# a comment
highspy==1.15.1
Jinja2[i18n]==3.1.6 ; python_version >= "3.8"
numpy==2.5.3 \\
    --hash=sha256:abc
pyyaml==6.0.3 # trailing remark
-r other.txt
--index-url https://example.invalid/simple
requests>=2.0
flask
"""
    pins, loose = pc.read_requirements(text)
    assert pins == [("highspy", "1.15.1"), ("Jinja2", "3.1.6"), ("numpy", "2.5.3"), ("pyyaml", "6.0.3")]
    assert loose == ["requests>=2.0", "flask"]


def test_exact_npm_pins_are_read_and_a_range_is_not_checked():
    package = json.dumps(
        {
            "name": "x",
            "dependencies": {"highs": "1.15.3", "caret": "^1.0.0", "tag": "latest"},
            "devDependencies": {"@scope/tool": "4.13.0", "tilde": "~2.0.0", "url": "github:owner/repo#abc", "twelve": "12.0.1"},
            "peerDependencies": {"not-read": "1.0.0"},
        }
    )
    pins, loose = pc.read_package_json(package)
    assert pins == [("highs", "1.15.3"), ("@scope/tool", "4.13.0"), ("twelve", "12.0.1")]
    assert loose == [("caret", "^1.0.0"), ("tag", "latest"), ("tilde", "~2.0.0"), ("url", "github:owner/repo#abc")]


@pytest.mark.parametrize("text", ["", "{not json", "[]", '{"dependencies": 5}', '{"dependencies": {"a": 5}}'])
def test_a_package_json_that_is_not_one_has_no_pins(text):
    pins, loose = pc.read_package_json(text)
    assert pins == [] and loose == []


def test_the_real_files_of_this_repository_are_read():
    workflows = sorted((REPO / ".github" / "workflows").glob("*.yml"))
    assert workflows
    parsed = [pc.parse_workflow(path.read_text(encoding="utf-8")) for path in workflows]
    actions = [pin for workflow in parsed for pin in workflow.actions]
    assert actions and all(re.fullmatch(r"[0-9a-f]{40}", pin.sha) for pin in actions)
    assert any(pin.name == "actions/checkout" and pin.tag for pin in actions)
    assert not any(workflow.unpinned for workflow in parsed)  # (the hardening tests insist on it; the check would say so)
    runtimes = {name: series for workflow in parsed for name, series in workflow.runtimes.items()}
    assert runtimes and all(re.fullmatch(r"[0-9]+(\.[0-9]+)?", one) for series in runtimes.values() for one in series)
    assert not [raw for workflow in parsed for _, raw in workflow.unreadable]  # (every series of this repository's own workflows can be read)
    python_pins, python_loose = pc.read_requirements((REPO / "requirements.txt").read_text(encoding="utf-8"))
    assert {"highspy", "numpy"} <= {name for name, _ in python_pins} and python_loose == []
    npm_pins, npm_loose = pc.read_package_json((REPO / "package.json").read_text(encoding="utf-8"))
    assert {"highs", "wrangler"} <= {name for name, _ in npm_pins} and npm_loose == []


@pytest.mark.parametrize(
    "text, line",
    [
        ("{not json", "- package.json: not checked (package.json is not JSON)"),
        ("", "- package.json: not checked (package.json is not JSON)"),
        ("[]", "- package.json: not checked (package.json is not a JSON object)"),
        ('{"dependencies": 5}', "- package.json: not checked (dependencies is not an object)"),
        ('{"devDependencies": ["a"]}', "- package.json: not checked (devDependencies is not an object)"),
        ('{"dependencies": {"a": 5}}', "- `a` (dependencies): not checked (its version is not text)"),
    ],
)
def test_a_package_json_that_is_damaged_is_not_checked_and_says_why_and_its_section_does_not_vanish(tmp_path, text, line):
    root = make_root(tmp_path, "jobs: {}\n", "otherlib==2.0.1\n")
    (root / "package.json").write_text(text, encoding="utf-8")
    result = run(tmp_path, root=root)
    assert result.code == 0
    report_text = report(result)
    assert line in report_text and "- no pin in package.json" not in report_text
    assert "1 not checked" in summary(report_text)


def test_a_package_json_with_good_pins_and_one_odd_entry_checks_the_good_ones(tmp_path):
    root = make_root(tmp_path, "jobs: {}\n", "", {"name": "x", "dependencies": {"examplejs": "1.2.0", "odd": 5}})
    text = report(run(tmp_path, root=root))
    assert "- `examplejs` 1.2.0: " in text and "- `odd` (dependencies): not checked (its version is not text)" in text


def test_a_package_json_that_is_not_there_is_still_said_to_be_missing(tmp_path):
    root = make_root(tmp_path, "jobs: {}\n", "otherlib==2.0.1\n")
    (root / "package.json").unlink()
    assert "- package.json is not there" in report(run(tmp_path, root=root))


NOT_UTF8 = bytes([0xFF, 0xFE]) + b' {"dependencies": {"examplejs": "1.2.0"}}'  # (bytes that are no UTF-8 text)


def test_a_package_json_that_is_not_utf8_text_is_not_checked_and_does_not_refuse_the_run(tmp_path):
    root = make_root(tmp_path, "jobs: {}\n", "examplelib==1.2.0\n")
    (root / "package.json").write_bytes(NOT_UTF8)
    result = run(tmp_path, root=root)
    assert result.code == 0
    text = report(result)
    assert "- package.json: not checked (package.json is not UTF-8 text)" in text and "- no pin in package.json" not in text
    assert "- `examplelib` 1.2.0: newer " in text  # (the rest is checked)
    assert str(tmp_path) not in "\n".join(log_lines(result.out))


def test_a_requirements_txt_that_is_not_utf8_text_is_not_checked_either(tmp_path):
    root = make_root(tmp_path, "jobs: {}\n", "")
    (root / "requirements.txt").write_bytes(NOT_UTF8)
    (root / "package.json").write_text('{"dependencies": {"exampleone": "1.0.0"}}', encoding="utf-8")
    text = report(run(tmp_path, root=root))
    assert "- requirements.txt: not checked (requirements.txt is not UTF-8 text)" in text and "- no pin in requirements.txt" not in text
    assert "- `exampleone` 1.0.0: " in text


def test_a_workflow_that_is_not_utf8_text_is_not_checked_and_the_other_workflows_still_are(tmp_path):
    root = make_root(tmp_path, f"steps:\n  - uses: x/y@{SHA_PINNED} # v2.0.0\n", "")
    (root / ".github" / "workflows" / "broken.yml").write_bytes(NOT_UTF8)
    result = run(tmp_path, net=action_net("x/y", "v2.0.0", "2026-01-01T00:00:00Z", SHA_PINNED), root=root)
    text = report(result)
    assert "- .github/workflows/broken.yml: not checked (broken.yml is not UTF-8 text)" in text
    assert f"- `x/y`: current (v2.0.0 at `{SHA_PINNED}`)" in text


# ---- versions and the rule of 14 days ----------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, key", [("1", (1, 0, 0, 0)), ("1.15.1", (1, 15, 1, 0)), ("2.5", (2, 5, 0, 0)), ("1.2.3.4", (1, 2, 3, 4)), ("10.0.0", (10, 0, 0, 0))])
def test_a_final_release_number_is_a_tuple_of_numbers(text, key):
    assert pc.version_key(text) == key


@pytest.mark.parametrize("text", ["", "1.0.0rc1", "1.0.0-beta.1", "1.0.0.dev3", "1.0.0.post1", "v1.0.0", "1.0.0+local", "1..0", "a.b.c", "1.0.0a1", None, 5, "1.2.3.4.5"])
def test_anything_but_a_final_release_number_is_not_a_version(text):
    assert pc.version_key(text) is None


def test_versions_compare_as_numbers_and_a_trailing_zero_changes_nothing():
    assert pc.version_key("1.10.0") > pc.version_key("1.9.9")
    assert pc.version_key("2.5") == pc.version_key("2.5.0")
    assert pc.version_key("1.0.1") > pc.version_key("1.0")


def candidate(text: str, released: str) -> pc.Candidate:
    return pc.Candidate(text, pc.version_key(text), utc(released))


def test_a_version_is_taken_when_it_is_at_least_14_days_old_to_the_second():
    exactly = candidate("1.1.0", "2026-10-04T10:00:03Z")  # (14 days to the second before NOW)
    almost = candidate("1.1.0", "2026-10-04T10:00:04Z")  # (one second short)
    assert pc.MIN_AGE_DAYS == 14
    assert pc.pick([exactly], pc.version_key("1.0.0"), NOW).ready == exactly
    taken = pc.pick([almost], pc.version_key("1.0.0"), NOW)
    assert taken.ready is None and taken.young == almost


def test_the_newest_version_that_is_old_enough_is_taken_whatever_the_order_and_a_newer_young_one_is_named():
    older, middle, newest_old, young = (
        candidate("1.1.0", "2026-05-01T00:00:00Z"),
        candidate("1.2.0", "2026-06-01T00:00:00Z"),
        candidate("1.3.0", "2026-08-01T00:00:00Z"),
        candidate("1.4.0", "2026-10-16T00:00:00Z"),
    )
    picked = pc.pick([middle, young, older, newest_old], pc.version_key("1.0.0"), NOW)
    assert picked.ready == newest_old and picked.young == young


def test_a_young_version_that_is_older_in_number_than_the_one_taken_is_no_news():
    old_enough = candidate("1.5.0", "2026-08-01T00:00:00Z")
    young_but_lower = candidate("1.4.0", "2026-10-17T00:00:00Z")  # (a patch of an older line, released lately)
    picked = pc.pick([old_enough, young_but_lower], pc.version_key("1.0.0"), NOW)
    assert picked.ready == old_enough and picked.young is None


def test_versions_that_are_not_newer_than_the_pin_are_left_out():
    versions = [candidate("1.0.0", "2025-01-01T00:00:00Z"), candidate("0.9.0", "2024-01-01T00:00:00Z"), candidate("1.0.0", "2026-10-17T00:00:00Z")]
    picked = pc.pick(versions, pc.version_key("1.0.0"), NOW)
    assert picked.ready is None and picked.young is None


def test_with_no_pin_to_compare_with_the_newest_old_enough_of_all_is_taken():
    versions = [candidate("1.0.0", "2025-01-01T00:00:00Z"), candidate("1.1.0", "2025-06-01T00:00:00Z")]
    assert pc.pick_all(versions, NOW).ready.text == "1.1.0"
    assert pc.pick_all([candidate("1.2.0", "2026-10-17T00:00:00Z")], NOW).young.text == "1.2.0"


def test_a_pin_that_is_not_a_final_release_number_has_nothing_that_is_newer_than_it():
    versions = [candidate("1.0.0", "2025-01-01T00:00:00Z"), candidate("1.1.0", "2025-06-01T00:00:00Z")]
    item = pc.judge_package("examplelib", "2.0.0rc1", versions, NOW)
    assert item.status == "not checked" and item.line.startswith("- `examplelib` 2.0.0rc1: not checked (")
    assert "not a final release number" in item.line


@pytest.mark.parametrize("version", ["2.0.0rc1", "1.0.0.post1", "1.0.0+cpu", "1.0.0a1", "1.0.0.dev3", "1.0.0b2"])
def test_a_python_pin_that_is_not_final_is_not_checked_and_the_registry_is_not_asked(tmp_path, version):
    root = make_root(tmp_path, "jobs: {}\n", f"examplelib=={version}\n")
    result = run(tmp_path, root=root)
    text = report(result)
    assert f"- `examplelib` {version}: not checked (the pin is not a final release number, so nothing can be said to be newer than it)" in text
    assert PYPI.format(name="examplelib") not in result.transport.urls  # (nothing to ask)
    assert summary(text) == "0 newer (14 days old or more), 0 newer but too young, 0 moved, 0 unreachable, 1 not checked; 0 pins checked"


def test_a_final_pin_is_still_compared_and_a_non_final_one_next_to_it_does_not_hide_it(tmp_path):
    root = make_root(tmp_path, "jobs: {}\n", "examplelib==1.2.0\notherlib==2.0.1rc1\n")
    text = report(run(tmp_path, root=root))
    assert "- `examplelib` 1.2.0: newer " in text and "- `otherlib` 2.0.1rc1: not checked (" in text


def test_a_release_in_the_future_is_young_and_has_no_negative_age():
    future = candidate("2.0.0", "2026-10-19T00:00:00Z")
    picked = pc.pick([future], pc.version_key("1.0.0"), NOW)
    assert picked.ready is None and picked.young == future and pc.age_days(future, NOW) == 0


# ---- the answers of the registries, as candidates ------------------------------------------------------------------------------------------------------------


def fixture_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_pypi_gives_the_final_releases_that_have_files_that_are_not_all_yanked():
    found = {c.text: c.released for c in pc.pypi_candidates(fixture_json("pypi-examplelib.json"), "examplelib")}
    assert sorted(found) == ["1.0.0", "1.2.0", "1.3.0", "1.4.0"]  # (1.3.1 is yanked, 1.5.0rc1 is a pre-release, 1.6.0 has no files)
    assert found["1.2.0"] == utc("2025-05-01T10:00:00Z")  # (the date of a release is that of its first file)


def test_a_release_with_one_file_yanked_and_one_not_is_a_release():
    document = {"info": {"name": "x"}, "releases": {"1.0.0": [{"upload_time_iso_8601": "2025-01-01T00:00:00Z", "yanked": True}, {"upload_time_iso_8601": "2025-01-02T00:00:00Z", "yanked": False}]}}
    (found,) = pc.pypi_candidates(document, "x")
    assert found.released == utc("2025-01-02T00:00:00Z")


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"info": {"name": "other"}, "releases": {}},
        {"info": {"name": "x"}},
        {"info": {"name": "x"}, "releases": []},
        {"info": {"name": "x"}, "releases": {"1.0.0": "no"}},
    ],
)
def test_a_pypi_answer_that_is_not_the_package_is_unreachable(document):
    with pytest.raises(common.Unreachable):
        pc.pypi_candidates(document, "x")


def test_a_pypi_file_with_a_date_that_cannot_be_read_is_left_out():
    document = {"info": {"name": "x"}, "releases": {"1.0.0": [{"upload_time_iso_8601": "last week", "yanked": False}], "1.1.0": [{"upload_time_iso_8601": "2025-01-02T00:00:00Z", "yanked": False}]}}
    assert [c.text for c in pc.pypi_candidates(document, "x")] == ["1.1.0"]


def test_npm_gives_the_final_versions_that_are_not_deprecated_with_their_publish_time():
    found = {c.text: c.released for c in pc.npm_candidates(fixture_json("npm-exampleone.json"), "exampleone")}
    assert sorted(found) == ["1.0.0", "1.1.0"]  # (1.2.0 is deprecated, 2.0.0-beta.1 is a pre-release)
    assert found["1.1.0"] == utc("2026-07-01T10:00:00Z")


@pytest.mark.parametrize(
    "document",
    [[], {"name": "other", "versions": {}, "time": {}}, {"name": "x", "versions": []}, {"name": "x", "versions": {}, "time": []}, {"versions": {}, "time": {}}],
)
def test_an_npm_answer_that_is_not_the_package_is_unreachable(document):
    with pytest.raises(common.Unreachable):
        pc.npm_candidates(document, "x")


def test_a_version_with_no_time_is_left_out():
    document = {"name": "x", "versions": {"1.0.0": {}, "1.1.0": {}}, "time": {"1.1.0": "2025-01-02T00:00:00.000Z"}}
    assert [c.text for c in pc.npm_candidates(document, "x")] == ["1.1.0"]


def test_github_releases_give_the_final_ones_by_their_tag_or_their_name():
    node = {c.text for c in pc.release_candidates(fixture_json("github-node-releases.json"))}
    assert node == {"25.0.0", "24.15.0", "24.14.0", "22.20.0"}  # (24.16.0-rc.1 is a pre-release)
    python = {c.text for c in pc.release_candidates(fixture_json("github-python-releases.json"))}
    assert python == {"3.13.1", "3.12.8", "3.12.7"}  # (3.14.0-rc.2 is a pre-release; the number after the hyphen of a tag is a build)


def test_github_releases_that_are_drafts_or_flagged_as_pre_releases_are_left_out():
    releases = [
        {"tag_name": "v1.0.0", "published_at": "2025-01-01T00:00:00Z", "prerelease": True, "draft": False},
        {"tag_name": "v1.1.0", "published_at": "2025-01-01T00:00:00Z", "prerelease": False, "draft": True},
        {"tag_name": "v1.2.0", "published_at": "2025-01-01T00:00:00Z", "prerelease": False, "draft": False},
        {"tag_name": "nightly", "name": "nightly build", "published_at": "2025-01-01T00:00:00Z"},
        "text",
        {"tag_name": "v1.3.0", "published_at": "soon"},
    ]
    assert [c.text for c in pc.release_candidates(releases)] == ["1.2.0"]


# ---- the actions: a newer commit, the same commit, a tag that moved ------------------------------------------------------------------------------------------


def action_net(repo: str, latest_tag: str, published: str, sha: str) -> Net:
    """The answers about one action: its releases (one), and the commit of that release's tag."""
    return Net({LATEST.format(repo=repo): reply(200, [release_json(latest_tag, published)]), COMMIT.format(repo=repo, tag=latest_tag): commit_answer(sha)})


def release_json(tag: str, published: str, **more) -> dict:
    return {"tag_name": tag, "name": tag, "published_at": published, "prerelease": False, "draft": False, **more}


def action_report(tmp_path, uses: str, net: Net, now=NOW) -> str:
    result = run(tmp_path, net=net, now=now, root=action_root(tmp_path, uses))
    assert result.code == 0
    (line,) = [line for line in report(result).splitlines() if line.startswith("- `x/y")]
    return line


def test_a_newer_release_of_an_action_is_named_with_its_commit_its_date_and_its_age(tmp_path):
    net = action_net("x/y", "v2.1.0", "2026-08-30T12:00:00Z", SHA_A)
    line = action_report(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0", net)
    assert line == f"- `x/y`: pinned `{SHA_PINNED}` (v2.0.0), newer release v2.1.0 at `{SHA_A}` (released 2026-08-30, 48 days ago)"


def test_a_newer_release_younger_than_14_days_is_too_young_and_says_when_it_counts(tmp_path):
    net = action_net("x/y", "v2.1.0", "2026-10-10T12:00:00Z", SHA_A)
    line = action_report(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0", net)
    assert line == f"- `x/y`: pinned `{SHA_PINNED}` (v2.0.0), newer release v2.1.0 at `{SHA_A}` is too young (released 2026-10-10, 7 days ago; it counts from 2026-10-24)"


def test_the_release_that_is_the_pinned_tag_at_the_pinned_commit_is_current(tmp_path):
    net = action_net("x/y", "v2.0.0", "2026-01-01T00:00:00Z", SHA_PINNED)
    assert action_report(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0", net) == f"- `x/y`: current (v2.0.0 at `{SHA_PINNED}`)"


def test_the_pinned_tag_that_now_points_at_another_commit_is_a_moved_tag(tmp_path):
    net = action_net("x/y", "v2.0.0", "2026-01-01T00:00:00Z", SHA_A)
    line = action_report(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0", net)
    assert line == f"- `x/y`: the tag v2.0.0 now points at `{SHA_A}`, not at the pinned `{SHA_PINNED}`"
    result = run(tmp_path / "again", net=net, root=action_root(tmp_path / "again", f"x/y@{SHA_PINNED} # v2.0.0"))
    assert summary(report(result)).startswith("0 newer (14 days old or more), 0 newer but too young, 1 moved,")


def test_a_pin_newer_than_the_latest_release_is_current_and_says_so(tmp_path):
    net = action_net("x/y", "v1.9.0", "2026-01-01T00:00:00Z", SHA_A)
    line = action_report(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0", net)
    assert line == f"- `x/y`: current (the latest release, v1.9.0, is older than the pinned v2.0.0)"


@pytest.mark.parametrize("tag", ["v4.0.0-beta.1", "v4.0.0-rc.2", "4.0.0rc1", "v4.0.0+build5", "v4.0.0.post1", "v4.0.0_hotfix", "v4.0.0a1"])
def test_a_tag_in_the_comment_that_is_not_a_final_release_number_is_kept_as_it_is_and_not_cut_short(tag):
    text = f"steps:\n  - uses: a/b@{SHA_A} # {tag}\n"
    (pin,) = pc.parse_workflow(text).actions
    assert pin.tag is None and pin.odd_tag == tag  # (it used to be cut to v4.0.0, the final release, and then reported as a tag that moved)


@pytest.mark.parametrize("comment, tag", [("v4.0.0", "v4.0.0"), ("v4", "v4"), ("4.1", "4.1"), ("v4.0.0 (pinned for the security fix)", "v4.0.0"), ("v4.0.0   # again", "v4.0.0")])
def test_a_final_tag_in_the_comment_is_read_whole_with_a_remark_after_it_or_not(comment, tag):
    (pin,) = pc.parse_workflow(f"steps:\n  - uses: a/b@{SHA_A} # {comment}\n").actions
    assert (pin.tag, pin.odd_tag) == (tag, None)


@pytest.mark.parametrize("comment", ["", "a branch", "main", "see the changelog", "latest"])
def test_a_comment_that_is_no_version_names_no_tag_and_no_odd_one(comment):
    (pin,) = pc.parse_workflow(f"steps:\n  - uses: a/b@{SHA_A} # {comment}\n").actions
    assert (pin.tag, pin.odd_tag) == (None, None)


def test_an_action_pinned_at_a_pre_release_tag_is_not_checked_and_the_repository_is_not_asked_about_it(tmp_path):
    releases = [release_json("v4.0.0", "2026-08-01T12:00:00Z")]
    net = releases_net(releases, {"v4.0.0": SHA_A})
    result = run(tmp_path, net=net, root=action_root(tmp_path, f"x/y@{SHA_PINNED} # v4.0.0-beta.1"))
    (line,) = [line for line in report(result).splitlines() if line.startswith("- `x/y")]
    assert line == f"- `x/y`: pinned `{SHA_PINNED}` at the tag `v4.0.0-beta.1`, which is not a final release number, so not compared with the releases"
    assert not [url for url in result.transport.urls if "x/y" in url]  # (nothing to ask)
    assert ", 0 moved," in summary(report(result)) and ", 1 not checked;" in summary(report(result))


def test_a_pre_release_tag_next_to_a_final_pin_of_the_same_repository_does_not_hide_the_final_one(tmp_path):
    workflow = f"steps:\n  - uses: x/y@{SHA_PINNED} # v4.0.0-beta.1\n  - uses: x/y/sub@{SHA_B} # v1.0.0\n"
    net = releases_net([release_json("v1.0.0", "2026-01-01T12:00:00Z")], {"v1.0.0": SHA_B})
    text = report(run(tmp_path, net=net, root=make_root(tmp_path, workflow)))
    assert "- `x/y`: pinned" in text and "not compared with the releases" in text
    assert f"- `x/y/sub`: current (v1.0.0 at `{SHA_B}`)" in text


def test_a_pin_with_no_tag_in_its_comment_is_compared_by_commit_only(tmp_path):
    net = action_net("x/y", "v2.1.0", "2026-08-30T12:00:00Z", SHA_A)
    line = action_report(tmp_path, f"x/y@{SHA_PINNED}", net)
    assert line == f"- `x/y`: pinned `{SHA_PINNED}` (no tag named), the latest release v2.1.0 is at `{SHA_A}` (released 2026-08-30, 48 days ago)"
    same = action_net("x/y", "v2.1.0", "2026-08-30T12:00:00Z", SHA_PINNED)
    assert action_report(tmp_path / "same", f"x/y@{SHA_PINNED}", same) == f"- `x/y`: current (v2.1.0 at `{SHA_PINNED}`)"


@pytest.mark.parametrize("answer", [reply(404, {"message": "Not Found"}), reply(200, [])])
def test_a_repository_with_no_release_is_not_checked_and_is_not_unreachable(tmp_path, answer):
    net = Net({LATEST.format(repo="x/y"): answer})
    assert action_report(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0", net) == "- `x/y`: not checked (the repository has no release to compare with)"


@pytest.mark.parametrize(
    "replace",
    [
        {LATEST.format(repo="x/y"): reply(503)},
        {LATEST.format(repo="x/y"): reply(403, {"message": "API rate limit exceeded"})},
        {LATEST.format(repo="x/y"): TimeoutError("slow")},
        {LATEST.format(repo="x/y"): reply(200, "<html>maintenance</html>")},
        {COMMIT.format(repo="x/y", tag="v2.1.0"): reply(500)},
        {COMMIT.format(repo="x/y", tag="v2.1.0"): reply(200, {"message": "no sha"})},
    ],
)
def test_an_action_whose_answer_cannot_be_read_is_unreachable_and_never_newer(tmp_path, replace):
    net = action_net("x/y", "v2.1.0", "2026-08-30T12:00:00Z", SHA_A)
    net.replace.update(replace)
    line = action_report(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0", net)
    assert line.startswith("- `x/y`: unreachable (") and "newer" not in line


@pytest.mark.parametrize(
    "answer",
    [
        reply(200, [{"tag_name": "nightly", "published_at": "2026-08-30T12:00:00Z"}]),
        reply(200, [{"tag_name": "v2.1.0", "published_at": "yesterday"}]),
        reply(200, [{"tag_name": 5, "published_at": "2026-08-30T12:00:00Z"}]),
        reply(200, [{"tag_name": "v2.1.0", "published_at": "2026-08-30T12:00:00Z", "prerelease": True}, "text", 5, None]),
        reply(200, {"tag_name": "v2.1.0", "published_at": "2026-08-30T12:00:00Z"}),  # (an object where a list of releases is)
    ],
)
def test_a_list_of_releases_with_none_that_is_a_version_with_a_date_is_not_a_newer_pin(tmp_path, answer):
    net = action_net("x/y", "v2.1.0", "2026-08-30T12:00:00Z", SHA_A)
    net.replace[LATEST.format(repo="x/y")] = answer
    line = action_report(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0", net)
    assert line.startswith("- `x/y`: unreachable (") and "newer" not in line


def test_a_commit_that_is_not_forty_hex_digits_is_not_believed(tmp_path):
    net = action_net("x/y", "v2.1.0", "2026-08-30T12:00:00Z", "not-a-sha")
    assert action_report(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0", net).startswith("- `x/y`: unreachable (")


def releases_net(releases: list[dict], commits: dict[str, str]) -> Net:
    """The list of the releases of x/y, and the commit of each tag that is asked for."""
    replace = {LATEST.format(repo="x/y"): reply(200, releases)}
    replace.update({COMMIT.format(repo="x/y", tag=tag): commit_answer(sha) for tag, sha in commits.items()})
    return Net(replace)


def test_the_highest_final_release_is_compared_with_and_not_the_newest_one_that_was_made(tmp_path):
    releases = [
        release_json("v2.5.1", "2026-10-01T12:00:00Z"),  # (made last, and the lower number: a patch of an older line)
        release_json("v3.0.0", "2026-09-01T12:00:00Z"),  # (the highest, made earlier)
        release_json("v3.1.0-rc1", "2026-10-10T12:00:00Z", prerelease=True),
        release_json("v3.2.0", "2026-10-12T12:00:00Z", draft=True),
        release_json("nightly", "2026-10-15T12:00:00Z"),
        release_json("v2.9.0", "2026-08-01T12:00:00Z"),
    ]
    net = releases_net(releases, {"v3.0.0": SHA_A})
    result = run(tmp_path, net=net, root=action_root(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0"))
    (line,) = [line for line in report(result).splitlines() if line.startswith("- `x/y")]
    assert line == f"- `x/y`: pinned `{SHA_PINNED}` (v2.0.0), newer release v3.0.0 at `{SHA_A}` (released 2026-09-01, 46 days ago)"
    assert [url for url in result.transport.urls if "x/y" in url] == [LATEST.format(repo="x/y"), COMMIT.format(repo="x/y", tag="v3.0.0")]


def test_the_order_of_the_list_decides_nothing_and_of_two_releases_of_one_number_the_later_one_is_taken(tmp_path):
    releases = [release_json("v2.1.0", "2026-08-30T12:00:00Z"), release_json("v1.0.0", "2026-10-01T12:00:00Z"), release_json("2.1.0", "2026-09-02T12:00:00Z")]
    for order in (releases, releases[::-1]):
        net = releases_net(order, {"2.1.0": SHA_A})
        result = run(tmp_path / str(id(order)), net=net, root=action_root(tmp_path / str(id(order)), f"x/y@{SHA_PINNED} # v2.0.0"))
        (line,) = [line for line in report(result).splitlines() if line.startswith("- `x/y")]
        assert f"newer release 2.1.0 at `{SHA_A}` (released 2026-09-02" in line


def test_a_pin_at_the_highest_release_with_another_commit_is_moved_whatever_was_made_after_it(tmp_path):
    releases = [release_json("v2.0.0", "2026-01-01T12:00:00Z"), release_json("v1.9.1", "2026-09-01T12:00:00Z")]
    net = releases_net(releases, {"v2.0.0": SHA_A})
    (line,) = [line for line in report(run(tmp_path, net=net, root=action_root(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0"))).splitlines() if line.startswith("- `x/y")]
    assert line == f"- `x/y`: the tag v2.0.0 now points at `{SHA_A}`, not at the pinned `{SHA_PINNED}`"


def test_the_requests_for_an_action_are_the_list_of_its_releases_then_the_commit_of_the_highest_tag(tmp_path):
    net = action_net("x/y", "v2.1.0", "2026-08-30T12:00:00Z", SHA_A)
    result = run(tmp_path, net=net, root=action_root(tmp_path, f"x/y@{SHA_PINNED} # v2.0.0"))
    github = [url for url in result.transport.urls if "x/y" in url]
    assert github == [LATEST.format(repo="x/y"), COMMIT.format(repo="x/y", tag="v2.1.0")]


def test_two_pins_of_one_repository_ask_about_it_once(tmp_path):
    workflow = f"steps:\n  - uses: x/y@{SHA_PINNED} # v2.0.0\n  - uses: x/y/sub@{SHA_B} # v1.0.0\n"
    net = action_net("x/y", "v2.1.0", "2026-08-30T12:00:00Z", SHA_A)
    result = run(tmp_path, net=net, root=make_root(tmp_path, workflow))
    assert [url for url in result.transport.urls if "x/y" in url] == [LATEST.format(repo="x/y"), COMMIT.format(repo="x/y", tag="v2.1.0")]
    text = report(result)
    assert "- `x/y`: pinned" in text and "- `x/y/sub`: pinned" in text


# ---- a whole run on the recorded answers -----------------------------------------------------------------------------------------------------------------


def test_the_report_lists_every_kind_of_pin_with_what_is_newer_and_old_enough(tmp_path):
    text = report(run(tmp_path))
    expected = [
        f"- `example-org/example-action`: pinned `{SHA_PINNED}` (v2.0.0), newer release v2.1.0 at `{SHA_A}` (released 2026-08-30, 48 days ago)",
        f"- `example-org/setup-thing`: current (v1.4.2 at `{SHA_TWO}`)",
        f"- `example-org/setup-other`: pinned `{SHA_THREE}` (v3.0.0), newer release v3.1.0 at `{SHA_B}` is too young (released 2026-10-10, 7 days ago; it counts from 2026-10-24)",
        "- `other-org/unpinned@v4`: not pinned to a commit, so not checked",
        "- `examplelib` 1.2.0: newer 1.3.0 (released 2026-08-01, 78 days ago); a still newer 1.4.0 is only 3 days old",
        "- `otherlib` 2.0.1: current",
        "- `exampleone` 1.0.0: newer 1.1.0 (released 2026-07-01, 109 days ago)",
        "- `@example/tool` 2.0.0: current",
        "- `looselib` ^3.1.0: not an exact pin, so not checked",
        "- node 24.x (24.14.0 on this computer): newer 24.15.0 (released 2026-09-01, 46 days ago)",
        "- node, later series: 25.0.0 is too young (released 2026-10-14, 3 days ago; it counts from 2026-10-28)",
        "- python 3.12.x (3.12.7 on this computer): newer 3.12.8 (released 2026-09-05, 43 days ago)",
        "- python, later series: 3.13.1 (released 2026-09-10, 38 days ago)",
    ]
    lines = [line for line in text.splitlines() if line.startswith("- ")]
    assert lines == expected


def test_the_summary_counts_what_is_newer_too_young_moved_unreachable_and_not_checked(tmp_path, capsys):
    result = run(tmp_path)
    assert summary(report(result)) == "5 newer (14 days old or more), 1 newer but too young, 0 moved, 0 unreachable, 2 not checked; 9 pins checked"
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "pins-check: 5 newer (14 days old or more), 1 newer but too young, 0 moved, 0 unreachable, 2 not checked; 9 pins checked"
    assert len(lines) == 2 and lines[1].startswith("report: ") and lines[1].endswith(REPORT)


def test_the_report_says_that_it_changes_nothing_and_what_counts_as_newer(tmp_path):
    text = report(run(tmp_path))
    assert "changes no pin" in text and "at least 14 days old" in text and "open an issue by hand" in text
    assert text.startswith("# Pins check, 2026-10-18\n")


def test_nothing_the_registries_wrote_but_versions_dates_and_commits_gets_into_the_report(tmp_path):
    text = report(run(tmp_path))
    for hostile in ("ignore previous instructions", "Ignore previous instructions", "<script>", "alert(1)", "do not use this one"):
        assert hostile not in text


def test_a_run_changes_no_pin(tmp_path):
    root = tmp_path / "copy"
    root.mkdir()
    for path in FIXTURE_REPO.rglob("*"):
        target = root / path.relative_to(FIXTURE_REPO)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.write_bytes(path.read_bytes())

    def digests():
        return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*")) if path.is_file()}

    before = digests()
    run(tmp_path / "out", root=root)
    assert digests() == before


def test_only_get_requests_to_github_pypi_and_npm_are_made_and_no_robots_file_is_read(tmp_path):
    result = run(tmp_path)
    assert {urllib.parse.urlsplit(url).netloc for url in result.transport.urls} == {"api.github.com", "pypi.org", "registry.npmjs.org"}
    assert not any(url.endswith("/robots.txt") for url in result.transport.urls)
    assert all(url.startswith("https://") for url in result.transport.urls)


def test_a_whole_run_goes_a_request_a_second_with_the_projects_user_agent(tmp_path):
    result = run(tmp_path)
    starts = result.transport.starts
    assert len(starts) == 12 and starts == [float(n) for n in range(12)]
    assert {call[2]["User-Agent"] for call in result.transport.calls} == {USER_AGENT}


def test_the_scoped_npm_package_is_asked_for_by_its_encoded_name(tmp_path):
    result = run(tmp_path)
    assert "https://registry.npmjs.org/@example%2Ftool" in result.transport.urls and "https://registry.npmjs.org/exampleone" in result.transport.urls


def test_a_package_that_is_not_exactly_pinned_is_not_asked_for(tmp_path):
    result = run(tmp_path)
    assert not any("looselib" in url for url in result.transport.urls)


# ---- unreachable is never newer --------------------------------------------------------------------------------------------------------------------------

FAILURES = {
    "a 500": reply(500, "Internal Server Error"),
    "a 503": reply(503),
    "a 404": reply(404, "<html>nope</html>"),
    "a redirect": reply(301, "", {"Location": "https://elsewhere.invalid/"}),
    "html where json is expected": reply(200, "<html>maintenance</html>"),
    "an empty answer": reply(200, ""),
    "a timeout": TimeoutError("slow"),
}
SOURCES = {
    "a pinned action": (LATEST.format(repo="example-org/example-action"), "example-action"),
    "the commit of an action": (COMMIT.format(repo="example-org/example-action", tag="v2.1.0"), "example-action"),
    "a python package": (PYPI.format(name="examplelib"), "examplelib"),
    "an npm package": ("https://registry.npmjs.org/exampleone", "exampleone"),
    "a scoped npm package": ("https://registry.npmjs.org/@example%2Ftool", "tool"),
}


@pytest.mark.parametrize(
    "source, failure",
    [(source, failure) for source in SOURCES for failure in FAILURES if (source, failure) != ("a pinned action", "a 404")],  # (a 404 on the latest release is a repository with no release: see above)
)
def test_a_source_that_cannot_be_read_is_unreachable_and_never_newer(tmp_path, source, failure):
    url, name = SOURCES[source]
    answer = FAILURES[failure]
    result = run(tmp_path, net=Net({url: answer}))
    assert result.code == 0
    text = report(result)
    (line,) = [line for line in text.splitlines() if line.startswith("- ") and name in line.split(":")[0]]
    assert "unreachable (" in line and "newer" not in line
    assert ", 1 unreachable," in summary(text)
    assert (result.out / "pins-check.last-run").exists()


@pytest.mark.parametrize("failure", list(FAILURES))
@pytest.mark.parametrize("url, runtime", [(NODE, "node"), (PYTHON, "python")])
def test_a_list_of_releases_that_cannot_be_read_makes_the_runtime_unreachable(tmp_path, url, runtime, failure):
    result = run(tmp_path, net=Net({url: FAILURES[failure]}))
    text = report(result)
    lines = [line for line in text.splitlines() if line.startswith(f"- {runtime}")]
    assert len(lines) == 1 and lines[0].startswith(f"- {runtime}: unreachable (")
    assert ", 1 unreachable," in summary(text)


def test_a_release_list_with_no_release_of_the_series_is_not_checked(tmp_path):
    only_other = [{"tag_name": "v22.20.0", "published_at": "2026-07-01T12:00:00Z", "prerelease": False, "draft": False}]
    text = report(run(tmp_path, net=Net({NODE: reply(200, only_other)})))
    assert "- node 24.x (24.14.0 on this computer): not checked (no release of the series in the list of releases)" in text


def test_a_run_where_nothing_can_be_read_still_finishes_and_leaves_its_stamp(tmp_path):
    down = {url: OSError("down") for url, _ in SOURCES.values()}
    down.update({NODE: OSError("down"), PYTHON: OSError("down")})
    for repo, tag in (("example-org/setup-thing", "v1.4.2"), ("example-org/setup-other", "v3.1.0")):
        down[LATEST.format(repo=repo)] = OSError("down")
    down.update({PYPI.format(name="otherlib"): OSError("down")})
    result = run(tmp_path, net=Net(down))
    assert result.code == 0
    text = report(result)
    assert "newer" not in "\n".join(line for line in text.splitlines() if line.startswith("- "))
    assert summary(text).startswith("0 newer (14 days old or more), 0 newer but too young, 0 moved, ")
    assert (result.out / "pins-check.last-run").read_text(encoding="utf-8") == "2026-10-18T10:00:03Z\n"


# ---- the local versions of Node and Python ------------------------------------------------------------------------------------------------------------------


def test_this_computer_up_to_date_with_the_newest_old_enough_release_of_the_series_is_current(tmp_path):
    text = report(run(tmp_path, local={"python": "3.12.8", "node": "24.15.0"}))
    assert "- node 24.x (24.15.0 on this computer): current (the newest release of the series that is 14 days old is 24.15.0)" in text
    assert "- python 3.12.x (3.12.8 on this computer): current (the newest release of the series that is 14 days old is 3.12.8)" in text


def test_a_version_of_this_computer_that_is_not_known_leaves_the_series_not_checked_and_names_the_newest(tmp_path):
    text = report(run(tmp_path, local={"python": "3.12.7", "node": None}))
    assert "- node 24.x (not found on this computer): not checked; the newest release of the series that is 14 days old is 24.15.0 (released 2026-09-01, 46 days ago)" in text
    assert summary(text).endswith("3 not checked; 8 pins checked")


def test_a_runtime_the_workflows_do_not_name_is_not_looked_up(tmp_path):
    root = make_root(tmp_path, "jobs: {}\n", "otherlib==2.0.1\n")
    result = run(tmp_path, root=root)
    assert NODE not in result.transport.urls and PYTHON not in result.transport.urls
    assert "- node" not in report(result) and "- python" not in report(result)


def test_a_young_release_of_the_series_is_named_when_nothing_old_enough_is_newer(tmp_path):
    releases = [
        {"tag_name": "v24.14.0", "published_at": "2026-06-01T12:00:00Z", "prerelease": False, "draft": False},
        {"tag_name": "v24.15.0", "published_at": "2026-10-12T12:00:00Z", "prerelease": False, "draft": False},
    ]
    text = report(run(tmp_path, net=Net({NODE: reply(200, releases)})))
    assert "- node 24.x (24.14.0 on this computer): newer 24.15.0 is too young (released 2026-10-12, 5 days ago; it counts from 2026-10-26)" in text
    assert "- node, later series" not in text  # (none is out)
    assert summary(text) == "4 newer (14 days old or more), 2 newer but too young, 0 moved, 0 unreachable, 2 not checked; 9 pins checked"


def test_the_node_version_of_this_computer_is_asked_of_node_itself(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="v24.14.0\n", stderr="")

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    monkeypatch.setattr(pc.shutil, "which", lambda name: "C:/tools/node.exe" if name == "node" else None)
    versions = pc.local_versions()
    assert versions["node"] == "24.14.0" and versions["python"] == pc.platform.python_version()
    assert calls == [["C:/tools/node.exe", "--version"]]


@pytest.mark.parametrize("outcome", ["missing", "fails", "garbage", "hangs"])
def test_a_node_that_cannot_be_asked_is_not_found(monkeypatch, outcome):
    monkeypatch.setattr(pc.shutil, "which", lambda name: None if outcome == "missing" else "node")

    def fake_run(command, **kwargs):
        if outcome == "hangs":
            raise subprocess.TimeoutExpired(command, 15)
        if outcome == "fails":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="boom")
        return subprocess.CompletedProcess(command, 0, stdout="not a version", stderr="")

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    assert pc.local_versions()["node"] is None


def two_series_workflow() -> str:
    return (
        "jobs:\n  a:\n    steps:\n"
        '      - uses: setup\n        with:\n          python-version: "3.11"\n'
        '      - uses: setup\n        with:\n          python-version: "3.12"\n'
        "      - uses: setup\n        with:\n          node-version: ${{ matrix.node }}\n"
        "      - uses: setup\n        with:\n          node-version: lts/*\n"
    )


def test_every_series_the_workflows_name_is_looked_up_and_the_list_of_releases_is_asked_for_once(tmp_path):
    root = make_root(tmp_path, two_series_workflow())
    result = run(tmp_path, root=root, local={"python": "3.12.7", "node": "24.14.0"})
    text = report(result)
    assert "- python 3.11.x (" in text and "- python 3.12.x (3.12.7 on this computer): " in text
    assert result.transport.urls.count(PYTHON) == 1  # (one list of the releases of Python, two series judged from it)


def test_a_series_of_another_line_than_the_version_of_this_computer_is_not_compared_with_it(tmp_path):
    root = make_root(tmp_path, two_series_workflow())
    text = report(run(tmp_path, root=root, local={"python": "3.12.7", "node": None}))
    (line,) = [line for line in text.splitlines() if line.startswith("- python 3.11.x")]
    assert "not checked" in line and "3.12.7 on this computer, which is another series" in line


def test_a_version_read_from_a_file_by_the_workflow_is_not_checked_and_the_report_says_so(tmp_path):
    workflow = "jobs:\n  a:\n    steps:\n      - uses: setup\n        with:\n          node-version-file: .nvmrc\n          python-version-file: pyproject.toml\n"
    result = run(tmp_path, root=make_root(tmp_path, workflow), local={"python": "3.12.7", "node": "24.14.0"})
    text = report(result)
    why = "the version is read from a file by the workflow, which this check does not follow"
    assert f"- node-version-file `.nvmrc` (test.yml): not checked ({why})" in text
    assert f"- python-version-file `pyproject.toml` (test.yml): not checked ({why})" in text
    assert NODE not in result.transport.urls and PYTHON not in result.transport.urls  # (nothing to look up)


def test_a_series_that_cannot_be_read_is_not_checked_and_the_report_says_which_file_and_what_it_said(tmp_path):
    root = make_root(tmp_path, two_series_workflow())
    result = run(tmp_path, root=root, local={"python": "3.12.7", "node": "24.14.0"})
    text = report(result)
    assert "- node-version `${{ matrix.node }}` (test.yml): not checked (it is not a plain series such as 24 or 3.12, so there is nothing to look up)" in text
    assert "- node-version `lts/*` (test.yml): not checked (it is not a plain series such as 24 or 3.12, so there is nothing to look up)" in text
    assert NODE not in result.transport.urls  # (no series of Node could be read: its releases are not asked for)
    assert ", 4 not checked;" in summary(text)  # (the two versions that cannot be read, Python 3.11 on a computer that runs 3.12, and `setup`, which is not pinned to a commit)


# ---- the stamp, the files and the arguments ----------------------------------------------------------------------------------------------------------------


def test_the_stamp_is_written_when_the_run_finishes_and_the_release_build_can_read_it(tmp_path):
    result = run(tmp_path)
    assert (result.out / "pins-check.last-run").read_text(encoding="utf-8") == "2026-10-18T10:00:03Z\n"
    assert release.scheduled_warnings(result.out, NOW + 20 * DAY, names=["pins-check"], days=45) == []
    (warning,) = release.scheduled_warnings(result.out, NOW + 50 * DAY, names=["pins-check"], days=45)
    assert "pins-check" in warning and "50 days" in warning


def test_the_monthly_stamp_is_not_among_the_weekly_ones_the_release_build_insists_on():
    assert pc.NAME == "pins-check" and pc.NAME not in release.SCHEDULED_CHECKS


def test_the_stamp_takes_the_time_the_run_finishes(tmp_path):
    times = iter([NOW, NOW + datetime.timedelta(seconds=40)])
    fake_time = FakeTime()
    out = tmp_path / "checks"
    pc.main(
        ["--root", str(FIXTURE_REPO), "--out", str(out)],
        transport=FakeTransport(fake_time, Net()),
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        now=lambda: next(times, NOW + datetime.timedelta(seconds=40)),
        local_versions=LOCAL,
    )
    assert (out / "pins-check.last-run").read_text(encoding="utf-8") == "2026-10-18T10:00:43Z\n"
    assert (out / REPORT).exists()


def test_the_report_is_named_for_the_utc_time_the_run_began(tmp_path):
    plus_two = datetime.timezone(datetime.timedelta(hours=2))
    result = run(tmp_path, now=datetime.datetime(2026, 10, 18, 12, 0, 3, tzinfo=plus_two))
    assert result.report_name == REPORT == "pins-check-2026-10-18T100003Z.md"
    assert [path.name for path in result.out.glob("*.md")] == [REPORT]


def test_a_second_run_of_the_day_leaves_the_first_report_as_it_was(tmp_path):
    first = run(tmp_path)
    before = report(first)
    second = run(tmp_path, now=NOW + datetime.timedelta(hours=3), net=Net({PYPI.format(name="examplelib"): reply(500)}))
    assert sorted(path.name for path in second.out.glob("*.md")) == [REPORT, "pins-check-2026-10-18T130003Z.md"]
    assert report(first) == before and ", 0 unreachable," in summary(before) and ", 1 unreachable," in summary(report(second))


def test_a_report_is_never_overwritten_not_even_by_a_run_in_the_same_second(tmp_path):
    first = run(tmp_path)
    before = report(first)
    second = run(tmp_path)
    third = run(tmp_path)
    stem = REPORT.removesuffix(".md")
    assert sorted(path.name for path in first.out.glob("*.md")) == sorted([REPORT, f"{stem}-2.md", f"{stem}-3.md"])
    assert (second.report_name, third.report_name) == (f"{stem}-2.md", f"{stem}-3.md")
    assert report(first) == before


def test_a_report_of_that_name_that_someone_made_is_not_replaced_whatever_it_holds(tmp_path):
    out = tmp_path / "checks"
    out.mkdir()
    (out / REPORT).write_text("kept\n", encoding="utf-8")
    result = run(tmp_path)
    assert (out / REPORT).read_text(encoding="utf-8") == "kept\n" and result.report_name == REPORT.removesuffix(".md") + "-2.md"


def test_the_run_needs_no_account_and_says_who_runs_it_by_the_about_page_of_the_site(tmp_path):
    result = run(tmp_path)
    assert result.code == 0 and result.transport.calls
    assert {call[2]["User-Agent"] for call in result.transport.calls} == {USER_AGENT}
    assert "(+https://trioforge.pages.dev/about/;" in USER_AGENT


def test_another_contact_page_can_be_given_and_it_is_the_one_the_user_agent_carries(tmp_path):
    result = run(tmp_path, "--contact", "https://example.invalid/hello/")
    (agent,) = {call[2]["User-Agent"] for call in result.transport.calls}
    assert agent != USER_AGENT and "(+https://example.invalid/hello/;" in agent


@pytest.mark.parametrize("contact", ["", "no-address", "ftp://example.invalid/", "https://user:secret@example.invalid/", "https://example.invalid/a b", "https://example.invalid/;x"])
def test_a_contact_that_is_not_an_address_refuses_the_run(tmp_path, capsys, contact):
    fake_time = FakeTime()
    transport = FakeTransport(fake_time, Net())
    argv = [f"--contact={contact}", "--root", str(FIXTURE_REPO), "--out", str(tmp_path / "checks")]
    assert pc.main(argv, transport=transport, clock=fake_time.clock, sleep=fake_time.sleep, now=lambda: NOW, local_versions=LOCAL) == 2
    err = capsys.readouterr().err
    assert "contact" in err.lower() and len(err.splitlines()) == 1 and transport.calls == [] and only_the_log(tmp_path / "checks")


def test_the_option_that_named_the_account_is_gone():
    with pytest.raises(SystemExit) as stop:
        pc.main(["--owner", "someone"])
    assert stop.value.code == 2


def test_a_root_with_nothing_to_check_refuses_the_run_in_one_line(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run(tmp_path, root=empty)
    err = capsys.readouterr().err
    assert result.code == 2 and err.startswith("pins-check: ") and len(err.splitlines()) == 1
    assert result.transport.calls == [] and not (result.out / "pins-check.last-run").exists()


def test_a_file_that_is_missing_is_said_in_the_report_and_the_others_are_checked(tmp_path):
    root = make_root(tmp_path, "", "otherlib==2.0.1\n")
    (root / "package.json").unlink()
    text = report(run(tmp_path, root=root))
    assert "- package.json is not there" in text and "- `otherlib` 2.0.1: current" in text


def test_the_report_goes_where_it_is_told_and_that_folder_is_made(tmp_path):
    result = run(tmp_path / "deep" / "er")
    assert (result.out / REPORT).is_file() and (result.out / "pins-check.last-run").is_file()


def test_the_report_is_text_with_unix_line_ends(tmp_path):
    raw = (run(tmp_path).out / REPORT).read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")


def test_an_unknown_option_is_a_usage_error():
    with pytest.raises(SystemExit) as stop:
        pc.main(["--no-such-option"])
    assert stop.value.code == 2


def test_a_write_that_fails_ends_the_run_in_one_line_and_leaves_no_stamp(tmp_path, capsys, monkeypatch):
    real = common.write_text_atomic

    def fail_on_report(path, text):
        if str(path).endswith(".md"):
            raise OSError("the disk is full")
        return real(path, text)

    monkeypatch.setattr(common, "write_text_atomic", fail_on_report)
    result = run(tmp_path)
    err = capsys.readouterr().err
    assert result.code == 2 and err.startswith("pins-check: ") and len(err.splitlines()) == 1
    assert not (result.out / "pins-check.last-run").exists()


def test_an_interrupted_run_ends_with_130_and_leaves_no_stamp(tmp_path):
    result = run(tmp_path, net=Net({PYPI.format(name="otherlib"): KeyboardInterrupt()}))
    assert result.code == 130 and not (result.out / "pins-check.last-run").exists()


# ---- the dry run ---------------------------------------------------------------------------------------------------------------------------------------


def real_folder_spellings(folder: Path) -> list[Path]:
    """The folder of the real checks as it can be written: as it is, with a dot, with a trailing separator, round a sub-folder, and (on Windows) in another case."""
    spellings = [folder, folder / ".", Path(str(folder) + os.sep), folder / "sub" / ".."]
    if sys.platform == "win32":
        spellings.append(Path(str(folder).swapcase()))
    return spellings


@pytest.mark.parametrize("abbreviation", ["--dry", "--dry-r", "--ou", "--roo", "--con"])
def test_an_option_is_not_taken_for_a_longer_one_that_begins_like_it(tmp_path, abbreviation):
    argv = ["--root", str(FIXTURE_REPO), abbreviation, str(tmp_path / "scratch")]
    with pytest.raises(SystemExit) as stopped:
        pc.main(argv, now=lambda: NOW, local_versions=LOCAL)
    assert stopped.value.code == 2


def test_an_abbreviated_dry_run_is_no_dry_run_that_could_be_guarded_it_is_refused_and_leaves_nothing_in_the_real_folder(tmp_path):
    folder = Path(os.environ["TRIOFORGE_CHECKS_DIR"])
    for argv in (
        ["--dry", str(FIXTURES), "--root", str(FIXTURE_REPO), "--out", str(folder)],
        ["--dry", str(FIXTURES), "--no-such-option"],
        ["--dr", str(FIXTURES), "--bogus"],
    ):
        with pytest.raises(SystemExit) as stopped:
            pc.main(argv, now=lambda: NOW, local_versions=LOCAL)
        assert stopped.value.code == 2, argv
        assert not folder.exists() or list(folder.iterdir()) == [], argv


def test_a_dry_run_cannot_write_into_the_folder_of_the_real_checks_however_it_is_spelled(tmp_path, capsys):
    folder = Path(os.environ["TRIOFORGE_CHECKS_DIR"])
    for spelling in real_folder_spellings(folder):
        argv = ["--dry-run", str(FIXTURES), "--root", str(FIXTURE_REPO), "--out", str(spelling)]
        assert pc.main(argv, now=lambda: NOW, local_versions=LOCAL) == 2, spelling
        err = capsys.readouterr().err
        assert err.startswith("pins-check: a dry run cannot write into the folder of the real checks") and len(err.splitlines()) == 1, spelling
    assert not folder.exists() or list(folder.iterdir()) == []  # (no report, no stamp, and not even a line of the log)
    assert pc.main(["--dry-run", str(FIXTURES), "--root", str(FIXTURE_REPO), "--out", str(tmp_path / "scratch")], now=lambda: NOW, local_versions=LOCAL) == 0


@pytest.mark.parametrize("option", ["--out", "--dry-run", "--root"])
@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_path_is_refused_and_is_not_the_working_folder(tmp_path, monkeypatch, option, empty):
    monkeypatch.chdir(tmp_path)
    fake_time = FakeTime()
    argv = ["--root", str(FIXTURE_REPO), "--out", str(tmp_path / "scratch")]
    if option == "--root":
        argv = argv[2:] + ["--root", empty]
    elif option == "--out":
        argv = argv[:2] + ["--out", empty]
    else:
        argv += ["--dry-run", empty]
    with pytest.raises(SystemExit) as stopped:
        pc.main(argv, transport=FakeTransport(fake_time, Net()), clock=fake_time.clock, sleep=fake_time.sleep, now=lambda: NOW, local_versions=LOCAL)
    assert stopped.value.code == 2
    assert sorted(path.name for path in tmp_path.iterdir()) == []  # (nothing was written in the working folder, and nothing else made there)


def test_a_dry_run_replays_the_recorded_answers_and_never_makes_a_network_request(tmp_path, monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError("a dry run asked for the real transport")

    monkeypatch.setattr(common, "real_transport", no_network)
    out = tmp_path / "scratch"
    code = pc.main(["--dry-run", str(FIXTURES), "--root", str(FIXTURE_REPO), "--out", str(out)], now=lambda: NOW)
    assert code == 0
    text = (out / REPORT).read_text(encoding="utf-8")
    assert summary(text) == "5 newer (14 days old or more), 1 newer but too young, 0 moved, 0 unreachable, 2 not checked; 9 pins checked"  # (the versions of this computer are the replay's)
    assert capsys.readouterr().out.splitlines()[0].startswith("pins-check: 5 newer")


def test_a_dry_run_must_say_where_to_write(tmp_path, capsys):
    assert pc.main(["--dry-run", str(FIXTURES), "--root", str(FIXTURE_REPO)], now=lambda: NOW) == 2
    assert "--out" in capsys.readouterr().err


def test_a_dry_run_of_a_folder_that_holds_no_recorded_answers_is_refused_in_one_line(tmp_path, capsys):
    assert pc.main(["--dry-run", str(tmp_path / "nothing-here"), "--root", str(FIXTURE_REPO), "--out", str(tmp_path / "o")], now=lambda: NOW) == 2
    err = capsys.readouterr().err
    assert err.startswith("pins-check: ") and len(err.splitlines()) == 1


def test_the_command_runs_on_recorded_answers_and_leaves_what_the_release_build_can_read(tmp_path):
    out = tmp_path / "scratch"
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", str(FIXTURES), "--root", str(FIXTURE_REPO), "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) == 2 and lines[0].startswith("pins-check: ") and lines[1].startswith("report: ") and done.stderr == ""
    stamp = (out / "pins-check.last-run").read_text(encoding="utf-8")
    assert re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z\n", stamp)
    assert release.scheduled_warnings(out, common.parse_utc(stamp) + 3 * DAY, names=["pins-check"], days=45) == []


def test_the_command_reports_a_usage_error_with_status_2(tmp_path):
    done = subprocess.run([sys.executable, str(SCRIPT), "--no-such-option"], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert done.returncode == 2 and done.stdout == ""
