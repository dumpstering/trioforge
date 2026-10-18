"""Tests for the scanner rules that keep the private seen flags, and a build made with them, out of the repository.

They run without the privacy key, so CI runs them too. Three things are refused:

* a tracked path with a ``build`` folder in it (``build/`` is where a build with seen flags is allowed to go,
  and it is git-ignored; a file there that was committed anyway is a finding);
* a ``.json`` file that holds a reason with the code ``seen-in-game`` (what the catalog builder writes for an
  item the maintainer has seen), in any layout of the JSON;
* the private exporter's output under any name: a JSON object with exactly the fields ``version``, ``license``
  and ``keys``, whose keys are item keys.

The reason code is joined from pieces in this file, like the log-shaped lines of the other privacy tests.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_privacy_helpers import (  # noqa: F401  (fixtures are used by name)
    ROOT,
    commit,
    git,
    gitenv,
    keyfile,
    parse_output,
    repo,
    rules,
    run_cli,
    scan_blob,
    write,
)
from trioforge.privacy import scan as S

CODE = "seen" + "-in-" + "game"
FLAGS = {"version": "2026-10-14", "license": "CC BY-SA 4.0", "keys": ["w1001", "w99638"]}


def finding(path, line, col, rule):
    return S.Finding(path, line, col, rule, "-")


def reason_json(text, layout="compact"):
    """A catalog fragment with one seen reason, written the way different tools lay JSON out."""
    item = {"key": "w1", "evidence": {"level": "strict", "reasons": [{"code": CODE, "seal": "measured", "text": text}]}}
    if layout == "compact":
        return json.dumps({"items": [item]}, separators=(",", ":")) + "\n"
    if layout == "spaced":
        return json.dumps({"items": [item]}) + "\n"
    if layout == "indented":
        return json.dumps({"items": [item]}, indent=2) + "\n"
    raise AssertionError(layout)


# ---- a tracked path with a build folder --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "build/catalog.json",
        "build/catalog-with-seen/catalog.json",
        "site/build/index.html",
        "a/b/build/c.txt",
        "Build/x.txt",
        "BUILD/x.txt",
        "build\\x.txt",
        "pipeline\\build\\x.txt",
        "build /x.txt",
        "build./x.txt",
        "build",
        "docs/build",
    ],
)
def test_a_path_with_a_build_folder_is_a_finding(path):
    assert scan_blob(path, b"nothing here\n") == [finding(path, 0, 0, "build-path")]


@pytest.mark.parametrize(
    "path",
    [
        "docs/build-notes.md",
        "buildx/x.txt",
        "rebuild/x.txt",
        "build.py",
        "scripts/build.sh",
        "pipeline/trioforge/build_tools.py",
        "builds/x.txt",
        "x/build-1/y.txt",
        "x/.build/y.txt",
        "src/prebuild/y.txt",
    ],
)
def test_a_path_that_only_looks_like_it_is_not(path):
    assert scan_blob(path, b"nothing here\n") == []


def test_a_build_file_is_still_read_so_that_a_name_in_it_is_found_too():
    result = scan_blob("build/notes.txt", b"nothing\nZorblax was here\n")  # the invented name is on the test denylist
    assert [(f.line, f.rule) for f in result] == [(0, "build-path"), (2, "denylist")]


def test_a_staged_build_file_is_refused_through_the_command_line(repo, keyfile):
    write(repo, "build/catalog-with-x/catalog.json", "{}\n")
    git(repo, "add", "-f", "build/catalog-with-x/catalog.json")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert [(f["path"], f["rule"]) for f in parse_output(done.stdout)] == [("build/catalog-with-x/catalog.json", "build-path")]


def test_a_build_file_deleted_long_ago_is_still_found_in_history(repo, keyfile):
    write(repo, "build/old.txt", "x\n")
    git(repo, "add", "-f", "build/old.txt")
    commit(repo, "add")
    git(repo, "rm", "-q", "build/old.txt")
    commit(repo, "remove")
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert done.returncode == 1
    # history lists the folder as well as the file
    assert {(f["path"], f["rule"]) for f in parse_output(done.stdout)} == {("build", "build-path"), ("build/old.txt", "build-path")}


def test_an_untracked_build_file_is_not_scanned_when_git_ignores_it(repo, keyfile):
    write(repo, ".gitignore", "build/\n")
    write(repo, "build/x.json", "{}\n")
    write(repo, "ok.txt", "fine\n")
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout


# ---- a seen reason in a .json file --------------------------------------------------------------------------------


@pytest.mark.parametrize("layout", ["compact", "spaced", "indented"])
def test_a_json_file_with_a_seen_reason_is_a_finding_in_any_layout(layout):
    result = scan_blob("derived/catalog.json", reason_json("Seen in game.", layout).encode("utf-8"))
    assert rules(result) == ["seen-reason"]
    assert result[0].line >= 1 and result[0].tag == "-"


def test_a_seen_reason_is_found_on_the_line_and_column_where_it_is():
    text = '{\n "items": [\n  {"key":"w1","evidence":{"level":"strict","reasons":[{"code":"' + CODE + '","seal":"measured"}]}}\n ]\n}\n'
    (found,) = scan_blob("derived/catalog.json", text.encode("utf-8"))
    assert (found.line, found.col, found.rule) == (3, text.splitlines()[2].index('"code"') + 1, "seen-reason")


def test_a_seen_reason_hidden_by_json_escapes_is_found():
    spelled = '{"co\\u0064e":"seen\\u002din-game","seal":"measured"}\n'
    assert rules(scan_blob("derived/catalog.json", spelled.encode("ascii"))) == ["seen-reason"]
    assert rules(scan_blob("derived/catalog.json", ('{"code" : "' + CODE.upper() + '"}\n').encode("ascii"))) == ["seen-reason"]


def test_a_seen_reason_with_a_suffix_is_found_too():
    assert rules(scan_blob("a.json", ('{"code":"' + CODE + ':Zone"}\n').encode("ascii"))) == ["seen-reason"]


@pytest.mark.parametrize("path", ["a.json", "A.JSON", "dir/b.Json", "lines.jsonl", "lines.ndjson"])
def test_the_rule_applies_to_json_files_by_extension_in_any_case(path):
    assert rules(scan_blob(path, reason_json("x").encode("utf-8"))) == ["seen-reason"]


@pytest.mark.parametrize("path", ["notes.md", "code.py", "page.html", "a.json.txt", "reasons.yml", "jsonish"])
def test_other_files_may_talk_about_the_reason(path):
    assert scan_blob(path, reason_json("x").encode("utf-8")) == []


@pytest.mark.parametrize(
    "text",
    [
        '{"labels": {"' + CODE + '": "Seen in game"}}\n',  # the code as a name, not as a reason code
        '{"enum": ["' + CODE + '", "community-report"]}\n',
        '{"code": "seen"}\n',
        '{"code": "' + CODE + 'box"}\n',
        '{"code": "unseen-in-game"}\n',
        '{"codes": "' + CODE + '"}\n',
        '{"text": "the code ' + CODE + ' is private"}\n',
    ],
)
def test_a_json_file_that_only_mentions_the_words_is_not_a_finding(text):
    assert scan_blob("rules/reasons.json", text.encode("utf-8")) == []


def test_the_reason_in_a_very_long_line_is_found():
    filler = '{"key":"w1","name":"x"},' * 60000  # one line of about 1.4 MB, longer than the scanner reads at once
    text = '{"items":[' + filler + '{"code":"' + CODE + '"}]}\n'
    assert rules(scan_blob("big.json", text.encode("utf-8"))) == ["seen-reason"]


def test_a_staged_catalog_with_a_seen_reason_is_refused_through_the_command_line(repo, keyfile):
    write(repo, "derived/catalog.json", reason_json("Seen in game."))
    git(repo, "add", "derived/catalog.json")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert [(f["path"], f["rule"]) for f in parse_output(done.stdout)] == [("derived/catalog.json", "seen-reason")]
    assert CODE not in done.stdout + done.stderr  # the output never carries what was matched


# ---- the exporter's output under any name ---------------------------------------------------------------------------


def flags_text(keys=FLAGS["keys"], **layout):
    return json.dumps({"version": FLAGS["version"], "license": FLAGS["license"], "keys": list(keys)}, **layout) + "\n"


@pytest.mark.parametrize(
    "path",
    ["fixtures/flags.json", "derived/anything.json", "x.json", "notes.txt", "fixtures/flags.dat", "docs/example.md", "seen_flags", "flags.json.bak"],
)
def test_the_exporter_output_is_refused_under_any_name(path):
    assert scan_blob(path, flags_text(indent=1).encode("utf-8")) == [finding(path, 0, 0, "seen-export")]


@pytest.mark.parametrize("layout", [{}, {"indent": 1}, {"indent": 2}, {"indent": 4}, {"separators": (",", ":")}, {"indent": "\t"}])
def test_the_exporter_output_is_refused_in_any_layout(layout):
    assert rules(scan_blob("flags.json", flags_text(**layout).encode("utf-8"))) == ["seen-export"]


def test_the_exporter_output_is_refused_with_other_line_ends_a_byte_order_mark_or_utf_16():
    text = flags_text(indent=1)
    for data in (
        text.replace("\n", "\r\n").encode("utf-8"),
        b"\xef\xbb\xbf" + text.encode("utf-8"),
        "\ufeff".encode("utf-16-le") + text.encode("utf-16-le"),
        text.encode("utf-16-le"),
        "\n\n  ".encode("utf-8") + text.encode("utf-8"),
    ):
        assert rules(scan_blob("flags.json", data)) == ["seen-export"], data[:12]


def test_research_only_item_keys_and_an_empty_list_count_as_the_same_shape():
    assert rules(scan_blob("a.json", flags_text(keys=["w1", "rsky-gear-1"]).encode("utf-8"))) == ["seen-export"]
    assert rules(scan_blob("a.json", flags_text(keys=[]).encode("utf-8"))) == ["seen-export"]


@pytest.mark.parametrize(
    "document",
    [
        {"version": "2026-10-14", "license": "CC BY-SA 4.0", "keys": ["not an item key"]},
        {"version": "2026-10-14", "license": "CC BY-SA 4.0", "keys": ["w1", 2]},
        {"version": "2026-10-14", "license": "CC BY-SA 4.0", "keys": "w1"},
        {"version": "2026-10-14", "license": "CC BY-SA 4.0", "keys": {"w1": 1}},
        {"version": "2026-10-14", "keys": ["w1"]},
        {"license": "CC BY-SA 4.0", "keys": ["w1"]},
        {"version": "2026-10-14", "license": "CC BY-SA 4.0", "reports": [{"key": "w1", "issue": "https://example.invalid/1"}]},
        {"version": "2026-10-14", "license": "CC BY-SA 4.0", "keys": ["w1"], "provenance": {}},
        ["w1", "w2"],
        {"data": {"version": "2026-10-14", "license": "CC BY-SA 4.0", "keys": ["w1"]}},
    ],
)
def test_other_json_documents_are_not_the_exporter_output(document):
    assert scan_blob("x.json", json.dumps(document).encode("utf-8")) == []


def test_text_that_is_not_json_is_left_alone():
    for data in (b'{"version": "2026-10-14", "keys": ["w1"', b"{not json}", b"[1, 2, 3]", b"plain words\n", b"{" * 5000, b'{"keys": ' + b"[" * 5000):
        assert scan_blob("x.txt", data) == [], data[:20]


def test_a_large_document_is_not_read_as_the_exporter_output():
    keys = [f"w{n}" for n in range(300000)]  # about 2.4 MB: no flags file is this big
    data = flags_text(keys=keys).encode("utf-8")
    assert len(data) > S.SHAPE_LIMIT
    assert scan_blob("x.json", data) == []


def test_the_exporter_output_is_refused_through_the_command_line(repo, keyfile):
    write(repo, "fixtures/flags-sample.json", flags_text(indent=1))
    git(repo, "add", "fixtures/flags-sample.json")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert [(f["path"], f["rule"]) for f in parse_output(done.stdout)] == [("fixtures/flags-sample.json", "seen-export")]
    assert "w1001" not in done.stdout + done.stderr


def test_the_exporter_output_is_found_in_history_too(repo, keyfile):
    write(repo, "a.json", flags_text(indent=1))
    git(repo, "add", "a.json")
    commit(repo, "add")
    git(repo, "rm", "-q", "a.json")
    commit(repo, "remove")
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert [(f["path"], f["rule"]) for f in parse_output(done.stdout)] == [("a.json", "seen-export")]


# ---- a clean tree stays clean ---------------------------------------------------------------------------------------


def test_ordinary_json_and_text_files_are_untouched_by_the_new_rules():
    catalog_like = json.dumps({"version": "2026-10-14", "license": "CC BY-SA 4.0", "items": [{"key": "w1", "evidence": {"level": "wiki", "reasons": []}}]})
    for path, data in (
        ("derived/catalog.json", catalog_like),
        ("rules/community-seen.json", json.dumps({"version": "2026-10-14", "reports": [{"key": "w1", "issue": "https://example.invalid/1"}]})),
        ("package.json", '{"name": "x", "version": "1.0.0", "license": "MIT"}'),
        ("docs/notes.md", "build and test\n"),
    ):
        assert scan_blob(path, data.encode("utf-8")) == [], path


# ---- the ignore rules ------------------------------------------------------------------------------------------------


@pytest.fixture
def ignore_repo(tmp_path, gitenv):
    """A scratch repository that has this repository's own .gitignore."""
    work = tmp_path / "ignoring"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    shutil.copyfile(ROOT / ".gitignore", work / ".gitignore")
    return work


def ignored(work, *paths):
    done = subprocess.run(["git", "check-ignore", "-z", "--no-index", "--stdin"], cwd=work, input="\0".join(paths) + "\0", capture_output=True, text=True)
    assert done.returncode in (0, 1), done.stderr
    return sorted(part for part in done.stdout.split("\0") if part)


def test_gitignore_keeps_seen_files_out_of_the_working_tree_but_not_out_of_fixtures_or_the_community_list(ignore_repo):
    candidates = [
        "seen.json",
        "derived/seen.json",
        "derived/seen-flags.json",
        "private/my-seen-flags.json",
        "a/b/c/last-seen-items.json",
        "build/catalog-with-seen/catalog.json",
        "fixtures/seen-sample.json",
        "fixtures/client/seen.json",
        "tests/fixtures/seen.json",
        "rules/community-seen.json",
        "docs/unseen-notes.md",
        ".github/ISSUE_TEMPLATE/seen-in-game.yml",
        "seen.txt",
    ]
    assert ignored(ignore_repo, *candidates) == sorted(
        [
            "seen.json",
            "derived/seen.json",
            "derived/seen-flags.json",
            "private/my-seen-flags.json",
            "a/b/c/last-seen-items.json",
            "build/catalog-with-seen/catalog.json",
        ]
    )


def test_this_repositorys_gitignore_still_ignores_what_it_ignored_before(ignore_repo):
    assert ignored(ignore_repo, ".venv/x", "node_modules/x", "build/x", "sources/eqlwiki/2026-10-14/raw/x.gz", "dist/x", "sources/eqltools/x.json") == sorted(
        [".venv/x", "node_modules/x", "build/x", "sources/eqlwiki/2026-10-14/raw/x.gz", "dist/x", "sources/eqltools/x.json"]
    )
    assert ignored(ignore_repo, "derived/catalog.json", "rules/zone-aliases.json", "pipeline/trioforge/data/catalog.py") == []


def test_the_contributor_guide_lists_the_new_refusals():
    (line,) = [line for line in (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").splitlines() if line.startswith("- **Refused files**")]
    assert "`build`" in line and "`.json`" in line and "seen-flags.json" in line and "exporter" in line
