"""Tests for ``python -m trioforge.community``, the command that keeps ``rules/community-seen.json``.

``add --key wNNN --issue N --kind seen|tier --screenshot-checked`` records a report that a maintainer has checked a screenshot of the item window for; ``retract --issue N
--reason R`` moves the entries of an issue to ``retracted``. Every write is atomic and keeps the file sorted. The command prints the counts and the entry it made or moved and
nothing else; a refusal is one line on standard error, exit status 2, and the file as it was. The address of an issue is built from the owner of the build, never stored.

The tests run on a repository of their own (a small catalog of invented items and a rules folder under ``tmp_path``) with the day fixed, so they never touch this checkout.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from trioforge import community
from trioforge.data.catalog import load_community_keys
from trioforge.privacy.scan import scan_bytes
from trioforge.site import build as site_build

REPO = Path(__file__).resolve().parents[2]
TODAY = "2026-10-18"
LATER = "2026-10-19"
CHECK = "item-window-screenshot"
ITEMS = [
    {"key": "w910001", "name": "Zorblax Cap", "slots": ["HEAD"]},
    {"key": "w910002", "name": "Quuxen Ring", "slots": ["FINGER"]},
    {"key": "w910003", "name": "Blarg Arrow", "slots": ["AMMO"]},  # a slot that no place of a kit has
    {"key": "w910004", "name": "Plain Rock", "slots": []},  # no slot at all
    {"key": "w910005", "name": "Zorblax Blade", "slots": ["PRIMARY", "SECONDARY"]},
    {"key": "w2", "name": "Short Key Cap", "slots": ["HEAD"]},
    {"key": "w10", "name": "Longer Key Cap", "slots": ["HEAD"]},
]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository root of its own: a catalog of invented items under derived/, an empty rules folder, and the module pointed at them with the day fixed."""
    root = tmp_path / "repo"
    (root / "derived").mkdir(parents=True)
    (root / "rules").mkdir()
    (root / "derived" / "catalog.json").write_text(json.dumps({"version": "2026-10-14", "items": ITEMS}), encoding="utf-8")
    monkeypatch.setattr(community, "REPO_ROOT", root)
    monkeypatch.setattr(community, "today_utc", lambda: TODAY)
    return root


def file_of(root: Path) -> Path:
    return root / "rules" / "community-seen.json"


def data_of(root: Path) -> dict:
    return json.loads(file_of(root).read_text(encoding="utf-8"))


def run(capsys, *args: str):
    code = community.main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def add(capsys, key="w910001", issue="5", kind="seen", *extra):
    return run(capsys, "add", "--key", key, "--issue", issue, "--kind", kind, "--screenshot-checked", *extra)


def entry(key="w910001", kind="seen", issue=5, date=TODAY):
    return {"key": key, "kind": kind, "issue": issue, "date": date, "check": CHECK}


def gone(key="w910001", issue=5, date=TODAY, reason="withdrawn"):
    return {"key": key, "issue": issue, "date": date, "reason": reason}


def disk_full(source, target):
    raise OSError("the disk is full")


def refused(capsys, root: Path, *args: str, mentions: tuple[str, ...] = ()) -> str:
    """Run a command that must be refused: exit status 2, nothing on standard output, one line on standard error, and the rules folder as it was."""
    before = {path.name: path.read_bytes() for path in sorted((root / "rules").iterdir())}
    code, out, err = run(capsys, *args)
    assert (code, out) == (2, ""), (code, out, err)
    assert err.startswith("error: ") and err.count("\n") == 1 and err.endswith("\n"), err
    for word in mentions:
        assert word in err, (word, err)
    assert {path.name: path.read_bytes() for path in sorted((root / "rules").iterdir())} == before  # (no file made, none changed, no temporary file left)
    return err


# ---- add -------------------------------------------------------------------------------------------------------------------------------


def test_add_makes_the_file_and_prints_the_entry_and_the_counts_and_nothing_else(repo, capsys):
    code, out, err = add(capsys)
    assert (code, err) == (0, "")
    assert out == 'added {"key":"w910001","kind":"seen","issue":5,"date":"2026-10-18","check":"item-window-screenshot"}\nreports 1, retracted 0\n'
    assert file_of(repo).read_bytes() == (
        b'{\n "version": "2026-10-18",\n "reports": [\n  {"key":"w910001","kind":"seen","issue":5,"date":"2026-10-18","check":"item-window-screenshot"}\n ],\n "retracted": []\n}\n'
    )


def test_the_entry_has_the_fields_of_the_form_in_their_order_and_the_date_of_today_in_utc(repo, capsys):
    add(capsys, "w910002", "12", "tier")
    assert data_of(repo) == {"version": TODAY, "reports": [entry("w910002", "tier", 12)], "retracted": []}
    assert list(data_of(repo)["reports"][0]) == ["key", "kind", "issue", "date", "check"]


def test_the_day_is_the_utc_day_of_the_clock_when_nothing_is_patched(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    (root / "derived").mkdir(parents=True)
    (root / "derived" / "catalog.json").write_text(json.dumps({"items": ITEMS}), encoding="utf-8")
    monkeypatch.setattr(community, "REPO_ROOT", root)
    before = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    assert add(capsys)[0] == 0
    after = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    assert data_of(root)["reports"][0]["date"] in {before, after}  # (the rules folder is made when it is missing)


def test_a_second_report_goes_to_the_file_sorted_by_item_and_then_by_issue(repo, capsys):
    add(capsys, "w910002", "9")
    add(capsys, "w910001", "6")
    code, out, _ = add(capsys, "w910001", "5", "tier")
    assert code == 0 and out.endswith("reports 3, retracted 0\n")
    assert [(e["key"], e["issue"]) for e in data_of(repo)["reports"]] == [("w910001", 5), ("w910001", 6), ("w910002", 9)]


def test_a_file_that_a_hand_edit_left_unsorted_is_sorted_by_the_next_write(repo, capsys):
    text = json.dumps({"version": "2026-10-01", "reports": [entry("w910002", "seen", 9, "2026-10-01"), entry("w910001", "seen", 5, "2026-10-01")], "retracted": [gone("w910005", 3), gone("w910004", 2)]})
    file_of(repo).write_text(text, encoding="utf-8")
    add(capsys, "w910001", "4")
    assert [(e["key"], e["issue"]) for e in data_of(repo)["reports"]] == [("w910001", 4), ("w910001", 5), ("w910002", 9)]
    assert [(e["key"], e["issue"]) for e in data_of(repo)["retracted"]] == [("w910004", 2), ("w910005", 3)]


def test_the_keys_are_sorted_as_text_like_the_keys_of_the_catalog(repo, capsys):
    add(capsys, "w2", "1")
    add(capsys, "w10", "2")
    assert [e["key"] for e in data_of(repo)["reports"]] == ["w10", "w2"]


def test_the_version_is_the_day_of_the_last_write_and_the_entries_keep_their_days(repo, capsys, monkeypatch):
    add(capsys, "w910001", "5")
    monkeypatch.setattr(community, "today_utc", lambda: LATER)
    add(capsys, "w910002", "6")
    assert data_of(repo) == {"version": LATER, "reports": [entry(), entry("w910002", "seen", 6, LATER)], "retracted": []}


def test_the_same_item_in_another_issue_and_another_item_in_the_same_issue_are_both_accepted(repo, capsys):
    assert add(capsys, "w910001", "5")[0] == 0
    assert add(capsys, "w910001", "6")[0] == 0
    assert add(capsys, "w910002", "5")[0] == 0
    assert [(e["key"], e["issue"]) for e in data_of(repo)["reports"]] == [("w910001", 5), ("w910001", 6), ("w910002", 5)]


def test_the_file_that_add_writes_is_read_back_by_the_catalog_builder(repo, capsys):
    add(capsys, "w910001", "5")
    add(capsys, "w910002", "6", "tier")
    assert load_community_keys(file_of(repo)) == frozenset({"w910001", "w910002"})


def test_a_wearable_with_two_slots_and_a_page_key_with_a_short_number_are_accepted(repo, capsys):
    assert add(capsys, "w910005", "3")[0] == 0 and add(capsys, "w2", "4")[0] == 0


# ---- add: what is refused ---------------------------------------------------------------------------------------------------------------


def test_add_without_screenshot_checked_is_refused_and_says_why(repo, capsys):
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", "seen", mentions=("--screenshot-checked", "screenshot"))
    assert not file_of(repo).exists()


def test_add_is_refused_for_an_item_the_catalog_does_not_have(repo, capsys):
    refused(capsys, repo, "add", "--key", "w999999", "--issue", "5", "--kind", "seen", "--screenshot-checked", mentions=("w999999", "catalog"))
    assert not file_of(repo).exists()


@pytest.mark.parametrize("key", ["w910003", "w910004"])
def test_add_is_refused_for_an_item_that_is_not_a_wearable(repo, capsys, key):
    refused(capsys, repo, "add", "--key", key, "--issue", "5", "--kind", "seen", "--screenshot-checked", mentions=(key, "wearable"))
    assert not file_of(repo).exists()


@pytest.mark.parametrize("key", ["bad key", "W910001", "910001", "w", "w91x", "", "w910001 ", "rBad", "w" + "9" * 16])
def test_add_is_refused_for_a_key_that_is_no_item_key_and_does_not_repeat_it(repo, capsys, key):
    err = refused(capsys, repo, "add", "--key", key, "--issue", "5", "--kind", "seen", "--screenshot-checked", mentions=("key",))
    assert len(key.strip()) < 4 or key.strip() not in err  # (a text the maintainer typed is not echoed back, whatever it is)


@pytest.mark.parametrize("issue", ["0", "-1", "1.5", "five", "", "05", "1e3", "9999999999", "#5", "5 "])
def test_add_is_refused_for_an_issue_that_is_not_a_whole_number_from_one(repo, capsys, issue):
    refused(capsys, repo, "add", "--key", "w910001", "--issue", issue, "--kind", "seen", "--screenshot-checked", mentions=("issue",))


@pytest.mark.parametrize("kind", ["other", "SEEN", "", "seen,tier"])
def test_add_is_refused_for_a_kind_that_is_not_on_the_list(repo, capsys, kind):
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", kind, "--screenshot-checked", mentions=("kind", "seen", "tier"))


@pytest.mark.parametrize("missing", ["--key", "--issue", "--kind"])
def test_add_is_refused_without_one_of_its_required_options(repo, capsys, missing):
    args = {"--key": "w910001", "--issue": "5", "--kind": "seen"}
    del args[missing]
    refused(capsys, repo, "add", *(word for pair in args.items() for word in pair), "--screenshot-checked", mentions=(missing,))


def test_a_second_report_of_the_same_item_and_issue_is_refused_whatever_else_differs(repo, capsys):
    add(capsys, "w910001", "5", "seen")
    before = file_of(repo).read_bytes()
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", "tier", "--screenshot-checked", mentions=("w910001", "5", "already"))
    assert file_of(repo).read_bytes() == before


def test_a_report_that_was_retracted_is_not_added_again(repo, capsys):
    add(capsys, "w910001", "5")
    run(capsys, "retract", "--issue", "5", "--reason", "wrong-item")
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", "seen", "--screenshot-checked", mentions=("retracted",))


def test_an_issue_that_was_retracted_takes_no_new_report_of_any_item(repo, capsys):
    """A retraction is final for the issue, not only for the item: a rejected issue must not be filled again with another item."""
    add(capsys, "w910001", "5")
    run(capsys, "retract", "--issue", "5", "--reason", "rejected")
    refused(capsys, repo, "add", "--key", "w910002", "--issue", "5", "--kind", "seen", "--screenshot-checked", mentions=("5", "retracted"))
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", "tier", "--screenshot-checked", mentions=("5", "retracted"))
    assert add(capsys, "w910002", "6")[0] == 0  # (another issue is a new report)


def test_a_slug_of_a_page_without_a_wiki_id_is_no_key_for_the_command_either(repo, capsys):
    refused(capsys, repo, "add", "--key", "rzorblax-ring", "--issue", "5", "--kind", "seen", "--screenshot-checked", mentions=("key",))


def test_add_is_refused_when_the_catalog_is_missing(repo, capsys):
    (repo / "derived" / "catalog.json").unlink()
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", "seen", "--screenshot-checked", mentions=("catalog",))


@pytest.mark.parametrize("text", ["not json", "[]", '{"items": 3}', '{"items": [{"key": "w910001"}]}', '{"items": [{"key": "w910001", "slots": "HEAD"}]}'])
def test_add_is_refused_when_the_catalog_is_not_one(repo, capsys, text):
    (repo / "derived" / "catalog.json").write_text(text, encoding="utf-8")
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", "seen", "--screenshot-checked", mentions=("catalog",))


def test_add_is_refused_for_a_file_of_the_old_form_and_says_how_to_convert_it(repo, capsys):
    file_of(repo).write_text(json.dumps({"version": TODAY, "reports": [{"key": "w910001", "issue": "https://example.invalid/issues/1"}]}), encoding="utf-8")
    refused(capsys, repo, "add", "--key", "w910002", "--issue", "5", "--kind", "seen", "--screenshot-checked", mentions=("old form", "convert"))


def test_add_is_refused_for_a_damaged_file_and_leaves_it_alone(repo, capsys):
    file_of(repo).write_text('{"version": "2026-10-18", "reports": [{"key": "w910001", "note": "free text"}], "retracted": []}', encoding="utf-8")
    refused(capsys, repo, "add", "--key", "w910002", "--issue", "5", "--kind", "seen", "--screenshot-checked")


def test_a_write_that_fails_leaves_the_file_as_it_was_and_no_temporary_file(repo, capsys, monkeypatch):
    add(capsys, "w910001", "5")
    with monkeypatch.context() as patched:
        patched.setattr(os, "replace", disk_full)
        refused(capsys, repo, "add", "--key", "w910002", "--issue", "6", "--kind", "seen", "--screenshot-checked", mentions=("community-seen.json",))
    assert [path.name for path in (repo / "rules").iterdir()] == ["community-seen.json"] and data_of(repo)["reports"] == [entry()]


# ---- retract ---------------------------------------------------------------------------------------------------------------------------


def three_reports(capsys):
    add(capsys, "w910001", "5")
    add(capsys, "w910002", "5", "tier")
    add(capsys, "w910001", "6")


def test_retract_moves_every_entry_of_the_issue_and_prints_what_it_moved_and_the_counts(repo, capsys, monkeypatch):
    three_reports(capsys)
    monkeypatch.setattr(community, "today_utc", lambda: LATER)
    code, out, err = run(capsys, "retract", "--issue", "5", "--reason", "withdrawn")
    assert (code, err) == (0, "")
    assert out == (
        'retracted {"key":"w910001","issue":5,"date":"2026-10-19","reason":"withdrawn"}\n'
        'retracted {"key":"w910002","issue":5,"date":"2026-10-19","reason":"withdrawn"}\n'
        "reports 1, retracted 2\n"
    )
    assert data_of(repo) == {
        "version": LATER,
        "reports": [entry("w910001", "seen", 6)],
        "retracted": [gone("w910001", 5, LATER), gone("w910002", 5, LATER)],
    }
    assert list(data_of(repo)["retracted"][0]) == ["key", "issue", "date", "reason"]


@pytest.mark.parametrize("reason", ["withdrawn", "wrong-item", "rejected", "duplicate"])
def test_each_reason_of_the_list_is_accepted(repo, capsys, reason):
    add(capsys)
    assert run(capsys, "retract", "--issue", "5", "--reason", reason)[0] == 0
    assert data_of(repo)["retracted"] == [gone(reason=reason)]


def test_the_retracted_entries_are_kept_sorted_and_the_reports_keep_their_order(repo, capsys):
    three_reports(capsys)
    add(capsys, "w2", "7")
    run(capsys, "retract", "--issue", "7", "--reason", "rejected")
    run(capsys, "retract", "--issue", "6", "--reason", "duplicate")
    run(capsys, "retract", "--issue", "5", "--reason", "withdrawn")
    assert [(e["key"], e["issue"]) for e in data_of(repo)["retracted"]] == [("w2", 7), ("w910001", 5), ("w910001", 6), ("w910002", 5)]
    assert data_of(repo)["reports"] == []


def test_a_retracted_item_is_no_community_key_any_more(repo, capsys):
    three_reports(capsys)
    assert load_community_keys(file_of(repo)) == frozenset({"w910001", "w910002"})
    run(capsys, "retract", "--issue", "5", "--reason", "wrong-item")
    assert load_community_keys(file_of(repo)) == frozenset({"w910001"})  # (w910001 is still reported in issue 6)
    run(capsys, "retract", "--issue", "6", "--reason", "wrong-item")
    assert load_community_keys(file_of(repo)) == frozenset()


def test_retract_of_an_issue_nobody_reported_is_refused(repo, capsys):
    three_reports(capsys)
    refused(capsys, repo, "retract", "--issue", "99", "--reason", "withdrawn", mentions=("99", "no report"))


def test_retract_when_there_is_no_file_is_refused(repo, capsys):
    refused(capsys, repo, "retract", "--issue", "5", "--reason", "withdrawn", mentions=("no report",))
    assert not file_of(repo).exists()


def test_retract_of_an_issue_that_is_retracted_already_says_so(repo, capsys):
    add(capsys)
    run(capsys, "retract", "--issue", "5", "--reason", "withdrawn")
    refused(capsys, repo, "retract", "--issue", "5", "--reason", "rejected", mentions=("5", "already retracted"))


@pytest.mark.parametrize("reason", ["other", "Withdrawn", "", "mistake", "withdrawn,rejected", "abuse"])
def test_retract_is_refused_for_a_reason_that_is_not_on_the_list_and_does_not_repeat_it(repo, capsys, reason):
    add(capsys)
    err = refused(capsys, repo, "retract", "--issue", "5", "--reason", reason, mentions=("reason", "withdrawn", "wrong-item", "rejected", "duplicate"))
    assert reason == "" or f"'{reason}'" not in err


@pytest.mark.parametrize("issue", ["0", "-5", "x", "", "2.0"])
def test_retract_is_refused_for_an_issue_that_is_not_a_whole_number_from_one(repo, capsys, issue):
    add(capsys)
    refused(capsys, repo, "retract", "--issue", issue, "--reason", "withdrawn", mentions=("issue",))


def test_retract_is_refused_without_a_reason_or_an_issue(repo, capsys):
    add(capsys)
    refused(capsys, repo, "retract", "--issue", "5", mentions=("--reason",))
    refused(capsys, repo, "retract", "--reason", "withdrawn", mentions=("--issue",))


def test_a_failing_write_while_retracting_leaves_the_file_as_it_was(repo, capsys, monkeypatch):
    three_reports(capsys)
    with monkeypatch.context() as patched:
        patched.setattr(os, "replace", disk_full)
        refused(capsys, repo, "retract", "--issue", "5", "--reason", "withdrawn", mentions=("community-seen.json",))
    assert len(data_of(repo)["reports"]) == 3 and data_of(repo)["retracted"] == []


# ---- the command line -----------------------------------------------------------------------------------------------------------------


def test_a_command_is_required_and_the_refusal_is_one_line(repo, capsys):
    refused(capsys, repo, mentions=("add", "retract"))
    refused(capsys, repo, "remove", "--key", "w910001")


SENTINEL = "Zorblax Sentinel"  # a made-up phrase, standing for a name that someone typed by mistake: no refusal may print it
ADD_WORDS = ["add", "--key", "w910001", "--issue", "5", "--kind", "seen", "--screenshot-checked"]
TYPED = {
    "an option the command does not have, with a sentence for its value": [*ADD_WORDS, "--note", f"reported by {SENTINEL}"],
    "the same with the value joined by an equals sign": [*ADD_WORDS, f"--note=reported by {SENTINEL}"],
    "an option whose name is the sentence": [*ADD_WORDS, "--" + SENTINEL.replace(" ", "-")],
    "a sentence for a command": [SENTINEL, "--issue", "5"],
    "a name for a command": [SENTINEL.split()[0], "--key", "w910001"],
    "a word after the command": ["add", SENTINEL, "--key", "w910001", "--issue", "5", "--kind", "seen", "--screenshot-checked"],
    "a value for the flag that takes none": [*ADD_WORDS[:-1], f"--screenshot-checked={SENTINEL}"],
    "a cut-short option with a sentence": ["add", "--ke", SENTINEL, "--issue", "5", "--kind", "seen", "--screenshot-checked"],
    "an option of retract that does not exist": ["retract", "--issue", "5", "--reason", "withdrawn", "--player", SENTINEL],
    "a sentence for the reason of retract": ["retract", "--issue", "5", "--reason", SENTINEL],
    "a sentence for the kind": ["add", "--key", "w910001", "--issue", "5", "--kind", SENTINEL, "--screenshot-checked"],
    "a sentence for the key": ["add", "--key", SENTINEL, "--issue", "5", "--kind", "seen", "--screenshot-checked"],
    "a sentence for the issue": ["add", "--key", "w910001", "--issue", SENTINEL, "--kind", "seen", "--screenshot-checked"],
    "two of them": [SENTINEL, "--note", SENTINEL, f"--{SENTINEL.split()[1]}", SENTINEL],
}


@pytest.mark.parametrize("words", list(TYPED.values()), ids=list(TYPED))
def test_no_text_that_was_typed_is_printed_back_by_a_refusal(repo, capsys, words):
    """A name typed by mistake on the command line (``--note "reported by <name>"``, a command that is a sentence) must not reach the console, a log or a screenshot of the
    maintainer's screen: argparse quotes what it did not understand, and a refusal of this command never does."""
    err = refused(capsys, repo, *words)
    assert "zorblax" not in err.lower() and "sentinel" not in err.lower() and "reported by" not in err.lower()


def test_a_refusal_of_a_command_line_says_the_form_in_one_fixed_line(repo, capsys):
    one = refused(capsys, repo, *ADD_WORDS, "--note", SENTINEL)
    assert "add" in one and "retract" in one and "--help" in one  # (it points at the two commands and at the help, whatever was typed)
    # the same line for every input that argparse would have quoted: a stray option of either command, a command that is a sentence
    assert one == refused(capsys, repo, "retract", "--issue", "5", "--reason", "withdrawn", "--player", SENTINEL) == refused(capsys, repo, SENTINEL)


def test_a_refusal_that_names_only_the_options_of_the_command_is_kept(repo, capsys):
    """What argparse says about an option the command has (the name is the command's own, not typed text) is informative and stays."""
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", "seen", mentions=("--screenshot-checked",))
    refused(capsys, repo, "add", "--key", "--issue", "5", "--kind", "seen", "--screenshot-checked", mentions=("--key", "expected one argument"))
    refused(capsys, repo, "retract", "--issue", "5", mentions=("--reason",))


def test_the_options_of_add_are_the_ones_of_the_brief(repo, capsys):
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", "seen", "--screenshot-checked", "--note", "free text")
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", "seen", "--screenshot-checked", "--second-issue", "6")


def test_an_option_written_short_is_not_taken_for_the_full_one(repo, capsys):
    """A flag that says a maintainer checked a screenshot is given in full, never by a prefix that happens to be unambiguous."""
    refused(capsys, repo, "add", "--key", "w910001", "--issue", "5", "--kind", "seen", "--screenshot")
    refused(capsys, repo, "add", "--ke", "w910001", "--issue", "5", "--kind", "seen", "--screenshot-checked")
    add(capsys)
    refused(capsys, repo, "retract", "--issue", "5", "--reas", "withdrawn")


def test_help_prints_the_two_commands(capsys):
    with pytest.raises(SystemExit) as caught:
        community.main(["--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "add" in out and "retract" in out


def test_the_module_runs_as_a_command_and_a_refusal_is_one_line_with_status_2():
    env = {**os.environ, "PYTHONPATH": str(REPO / "pipeline")}
    done = subprocess.run([sys.executable, "-m", "trioforge.community", "add"], capture_output=True, text=True, env=env, cwd=REPO, timeout=120)
    assert done.returncode == 2 and done.stdout == ""
    assert done.stderr.startswith("error: ") and done.stderr.count("\n") == 1
    helped = subprocess.run([sys.executable, "-m", "trioforge.community", "--help"], capture_output=True, text=True, env=env, cwd=REPO, timeout=120)
    assert helped.returncode == 0 and "retract" in helped.stdout


# ---- what the command prints and what the file holds ----------------------------------------------------------------------------------


def test_everything_the_command_prints_is_one_of_three_shapes_and_the_file_has_no_text_of_its_own(repo, capsys):
    printed = []
    for args in (
        ("add", "--key", "w910001", "--issue", "5", "--kind", "seen", "--screenshot-checked"),
        ("add", "--key", "w910002", "--issue", "5", "--kind", "tier", "--screenshot-checked"),
        ("add", "--key", "w910005", "--issue", "8", "--kind", "seen", "--screenshot-checked"),
        ("retract", "--issue", "5", "--reason", "rejected"),
    ):
        code, out, err = run(capsys, *args)
        assert code == 0 and err == ""
        printed += out.splitlines()
    shapes = (
        re.compile(r'added \{"key":"w[0-9]+","kind":"(?:seen|tier)","issue":[1-9][0-9]*,"date":"[0-9]{4}-[0-9]{2}-[0-9]{2}","check":"item-window-screenshot"\}'),
        re.compile(r'retracted \{"key":"w[0-9]+","issue":[1-9][0-9]*,"date":"[0-9]{4}-[0-9]{2}-[0-9]{2}","reason":"(?:withdrawn|wrong-item|rejected|duplicate)"\}'),
        re.compile(r"reports [0-9]+, retracted [0-9]+"),
    )
    assert printed and all(any(shape.fullmatch(line) for shape in shapes) for line in printed), printed
    text = file_of(repo).read_text(encoding="utf-8")
    assert "http" not in text and "github" not in text  # the file never holds an address
    words = set(re.findall(r"[A-Za-z][A-Za-z-]*", text))
    assert words <= {"version", "reports", "retracted", "key", "kind", "issue", "date", "check", "reason", "seen", "tier", "item-window-screenshot", "rejected", "w"}


def test_the_output_and_the_file_pass_the_scan_that_needs_no_key(repo, capsys):
    out = ""
    for args in (("add", "--key", "w910001", "--issue", "5", "--kind", "seen", "--screenshot-checked"), ("retract", "--issue", "5", "--reason", "duplicate")):
        out += run(capsys, *args)[1]
    assert scan_bytes("out.txt", out.encode("utf-8"), None, set(), set()) == []
    assert scan_bytes("rules/community-seen.json", file_of(repo).read_bytes(), None, set(), set()) == []


# ---- the address of an issue -----------------------------------------------------------------------------------------------------------


def test_the_address_of_an_issue_is_built_from_the_owner_of_the_build_and_the_number():
    assert community.issue_url("example-owner", 5) == "https://github.com/example-owner/trioforge/issues/5"
    assert community.issue_url("Ab1", 123456) == "https://github.com/Ab1/trioforge/issues/123456"


OWNERS = ["example-owner", "a", "A1-b2", "x" * 39, "", "owner", "OWNER", "Owner", "a b", "-x", "x-", "a--b", "a/b", "a.b", "x" * 40, "ünï", "a\n", "a?b", "../x", None, 5]


@pytest.mark.parametrize("owner", OWNERS)
def test_an_owner_is_accepted_when_the_site_build_accepts_it_and_refused_otherwise(owner):
    try:
        site_build.check_owner(owner, noindex=False)
        accepted = True
    except site_build.BuildError:
        accepted = False
    if accepted:
        assert community.issue_url(owner, 1) == f"{site_build._issues_url(owner)}/1"  # (the site and the reports name an issue the same way)
    else:
        with pytest.raises(community.CommunityError):
            community.issue_url(owner, 1)


@pytest.mark.parametrize("number", [0, -1, True, False, 1.0, "5", None, 10**10, [5]])
def test_an_issue_that_is_not_a_whole_number_from_one_has_no_address(number):
    with pytest.raises(community.CommunityError):
        community.issue_url("example-owner", number)


def test_the_repository_is_the_one_the_site_links_to():
    assert community.REPOSITORY == site_build.REPOSITORY
