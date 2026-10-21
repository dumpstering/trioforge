"""Tests for ``scripts/sources_check.py``, the weekly check of the sources that the Task Scheduler of the maintainer's computer runs.

It looks at three things and writes a report for a person to read: the recent changes of eqlwiki in the main namespace (only the pages that are items of the catalog,
shown as code, with their revision ids), the SHA-256 of the gear and the quest JSON of EQL Tools against the last run's, and whether the patch notes page changed, by
its hash. Nothing here touches the network: a fake clock and transport replay the answers recorded in ``fixtures/checks/sources`` (invented names and numbers, in the
shape of the real answers), or a ``--dry-run`` replays them from the folder, as the command does.

An answer that is not a 200, or is not JSON where JSON is expected, is "unreachable" and never "changed".
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
from checks_helpers import REPO, USER_AGENT, FakeTime, FakeTransport, query_of, reply

import checks_common as common
import sources_check as sc
from trioforge.precompute import release

FIXTURES = REPO / "fixtures" / "checks" / "sources"
SCRIPT = REPO / "scripts" / "sources_check.py"
NOW = datetime.datetime(2026, 10, 18, 10, 0, 3, tzinfo=datetime.timezone.utc)
DAY = datetime.timedelta(days=1)
WIKI, TOOLS = "eqlwiki.com", "eqltools.com"
REPORT = "sources-check-2026-10-18T100003Z.md"  # (the report of a run is named for the UTC time it began: NOW)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


GEAR, QUESTS = sha256(fixture("gear.json")), sha256(fixture("quests.json"))
PATCH_TEXT = json.loads(fixture("patch-notes.json"))["query"]["pages"][0]["revisions"][0]["slots"]["main"]["content"]
PATCH = sha256(PATCH_TEXT.encode("utf-8"))


def route(url: str) -> str | None:
    """Which recorded answer a request is for."""
    parts = urllib.parse.urlsplit(url)
    asked = query_of(url)
    if parts.path == "/robots.txt":
        return {WIKI: "robots-wiki", TOOLS: "robots-tools"}.get(parts.netloc)
    if parts.netloc == WIKI and parts.path == "/api.php":
        if asked.get("list") == "recentchanges":
            return "changes-2" if "rccontinue" in asked else "changes-1"
        if asked.get("prop") == "revisions":
            return "patch-notes"
    return {sc.GEAR_URL: "gear", sc.QUESTS_URL: "quests"}.get(url)


class Net:
    """The network of a run: the recorded answers, any of which a test can replace by another answer or by an exception to raise."""

    def __init__(self, **replace) -> None:
        self.answers = {
            "robots-wiki": reply(404),
            "robots-tools": reply(404),
            "changes-1": reply(200, fixture("recentchanges-1.json")),
            "changes-2": reply(200, fixture("recentchanges-2.json")),
            "patch-notes": reply(200, fixture("patch-notes.json")),
            "gear": reply(200, fixture("gear.json")),
            "quests": reply(200, fixture("quests.json")),
        }
        self.answers.update({name.replace("_", "-"): answer for name, answer in replace.items()})

    def __call__(self, url, headers):
        key = route(url)
        assert key is not None, f"a request the test did not expect: {url}"
        return self.answers[key]


def run(tmp_path, *extra, net=None, now=NOW, catalog=None):
    """One run of the command in this process, with the recorded answers (or ``net``) and a clock that only moves when the run sleeps."""
    fake_time = FakeTime()
    transport = FakeTransport(fake_time, net or Net())
    out = tmp_path / "checks"
    argv = ["--catalog", str(catalog or FIXTURES / "catalog.json"), "--out", str(out), *extra]
    before = {path.name for path in out.glob("*.md")}
    code = sc.main(argv, transport=transport, clock=fake_time.clock, sleep=fake_time.sleep, now=lambda: now)
    made = sorted({path.name for path in out.glob("*.md")} - before)  # (a run never replaces a report: the one it wrote is the one that is new)
    return SimpleNamespace(code=code, transport=transport, time=fake_time, out=out, report_name=made[0] if made else REPORT)


def report(result, name: str | None = None) -> str:
    """The report that this run wrote, or the one named."""
    return (result.out / (name or getattr(result, "report_name", REPORT))).read_text(encoding="utf-8")


def state(result) -> dict:
    return json.loads((result.out / "sources-check.state.json").read_text(encoding="utf-8"))


def summary(text: str) -> str:
    """The summary line of a report (the words that the command prints, after its name)."""
    (line,) = [line for line in text.splitlines() if line.startswith("Summary: ")]
    return line.removeprefix("Summary: ").removesuffix(".")


def changes_requests(result) -> list[dict]:
    return [query_of(url) for url in result.transport.urls if "list=recentchanges" in url]


# ---- the log: a trace of every run, for a task that has no window ---------------------------------------------------------------------------------------------


def log_lines(folder) -> list[str]:
    return (folder / "sources-check.log").read_text(encoding="utf-8").splitlines()


def only_the_log(folder) -> bool:
    """A refused run leaves no report, no record and no stamp: the one thing in its folder is the line of its log."""
    return sorted(path.name for path in folder.iterdir()) == ["sources-check.log"]


def test_a_finished_run_adds_one_line_to_the_log_with_its_counts_and_the_name_of_its_report(tmp_path):
    result = run(tmp_path)
    (line,) = log_lines(result.out)
    assert line.startswith("2026-10-18T10:00:03Z ok ")
    assert summary(report(result)) in line and re.search(r"; report sources-check-[0-9T:Z-]+\.md$", line)
    run(tmp_path, now=NOW + DAY)
    assert len(log_lines(result.out)) == 2


def test_a_run_in_which_a_source_was_unreachable_is_a_finished_run_in_the_log(tmp_path):
    result = run(tmp_path, net=Net(gear=reply(503)))
    (line,) = log_lines(result.out)
    assert " ok " in line and "1 unreachable" in line


def test_a_refused_run_leaves_a_refused_line_with_its_reason_and_no_stamp(tmp_path):
    result = run(tmp_path, "--contact", "not an address")
    assert result.code == 2
    (line,) = log_lines(result.out)
    assert line.startswith("2026-10-18T10:00:03Z refused --contact: ")
    assert not (result.out / "sources-check.last-run").exists()
    missing = run(tmp_path, catalog=tmp_path / "none.json")
    assert missing.code == 2 and " refused cannot read the catalog none.json" in log_lines(missing.out)[-1]


def test_a_run_that_crashed_leaves_an_error_line_with_the_kind_and_the_message_and_an_interrupted_one_says_so(tmp_path):
    crashed = run(tmp_path, net=Net(gear=RuntimeError("boom")))
    assert crashed.code == 2
    assert log_lines(crashed.out)[-1] == "2026-10-18T10:00:03Z error an unexpected fault (RuntimeError); run the check by hand to see what it was"
    interrupted = run(tmp_path, net=Net(gear=KeyboardInterrupt()))
    assert interrupted.code == 130
    assert log_lines(interrupted.out)[-1] == "2026-10-18T10:00:03Z interrupted interrupted"
    assert not (crashed.out / "sources-check.last-run").exists()


def test_the_log_of_a_crash_never_holds_the_message_of_the_fault_which_can_hold_a_path_of_this_computer(tmp_path, capsys):
    result = run(tmp_path, net=Net(gear=RuntimeError(f"cannot open {tmp_path / 'private' / 'file.txt'}")))
    assert result.code == 2
    (line,) = log_lines(result.out)
    assert str(tmp_path) not in line and "private" not in line and line.endswith(" error an unexpected fault (RuntimeError); run the check by hand to see what it was")
    assert "cannot open" in capsys.readouterr().err  # (what a person who runs the check by hand sees)


def test_a_command_line_that_is_wrong_leaves_a_refused_line_in_the_log_of_the_checks_folder(tmp_path):
    folder = Path(os.environ["TRIOFORGE_CHECKS_DIR"])
    with pytest.raises(SystemExit) as stopped:
        sc.main(["--days", "soon", "--out", str(tmp_path / "elsewhere")], now=lambda: NOW)
    assert stopped.value.code == 2
    (line,) = log_lines(folder)
    assert line.startswith("2026-10-18T10:00:03Z refused ") and "--days" in line and "must be a whole number of days" in line
    assert not (tmp_path / "elsewhere").exists()


def test_a_dry_run_that_is_refused_leaves_nothing_in_the_real_folder(tmp_path):
    folder = Path(os.environ["TRIOFORGE_CHECKS_DIR"])
    assert sc.main(["--dry-run", str(FIXTURES), "--catalog", str(FIXTURES / "catalog.json")], now=lambda: NOW) == 2  # (a dry run needs --out)
    assert not folder.exists() or list(folder.iterdir()) == []
    with pytest.raises(SystemExit):
        sc.main(["--dry-run", str(FIXTURES), "--days", "soon"], now=lambda: NOW)
    assert not folder.exists() or list(folder.iterdir()) == []


@pytest.mark.parametrize("abbreviation", ["--dry", "--dry-r", "--ou", "--cat", "--con"])
def test_an_option_is_not_taken_for_a_longer_one_that_begins_like_it(tmp_path, abbreviation):
    argv = ["--catalog", str(FIXTURES / "catalog.json"), abbreviation, str(tmp_path / "scratch")]
    with pytest.raises(SystemExit) as stopped:
        sc.main(argv, now=lambda: NOW)
    assert stopped.value.code == 2


def test_an_abbreviated_dry_run_is_no_dry_run_that_could_be_guarded_it_is_refused_and_leaves_nothing_in_the_real_folder(tmp_path):
    folder = Path(os.environ["TRIOFORGE_CHECKS_DIR"])
    for argv in (
        ["--dry", str(FIXTURES), "--catalog", str(FIXTURES / "catalog.json"), "--out", str(folder)],  # (an abbreviation of --dry-run that names the real folder)
        ["--dry", str(FIXTURES), "--days", "soon"],  # (and one with a command line that is wrong, which logs: not into the real folder)
        ["--dr", str(FIXTURES), "--bogus"],
    ):
        with pytest.raises(SystemExit) as stopped:
            sc.main(argv, now=lambda: NOW)
        assert stopped.value.code == 2, argv
        assert not folder.exists() or list(folder.iterdir()) == [], argv


def test_without_out_the_log_is_beside_the_stamp_in_the_folder_of_the_checks(tmp_path):
    folder = Path(os.environ["TRIOFORGE_CHECKS_DIR"])
    fake_time = FakeTime()
    code = sc.main(["--catalog", str(FIXTURES / "catalog.json")], transport=FakeTransport(fake_time, Net()), clock=fake_time.clock, sleep=fake_time.sleep, now=lambda: NOW)
    assert code == 0 and (folder / "sources-check.last-run").is_file()
    (line,) = log_lines(folder)
    assert " ok " in line


def test_the_log_of_a_run_keeps_the_last_200_lines(tmp_path):
    out = tmp_path / "checks"
    out.mkdir()
    (out / "sources-check.log").write_text("".join(f"2026-01-01T00:00:00Z ok old {n}\n" for n in range(250)), encoding="utf-8")
    result = run(tmp_path)
    lines = log_lines(result.out)
    assert len(lines) == 200 and lines[0].endswith("old 51") and lines[-1].startswith("2026-10-18T10:00:03Z ok ")


def test_a_log_that_cannot_be_written_does_not_change_the_outcome_of_a_run(tmp_path):
    (tmp_path / "checks" / "sources-check.log").mkdir(parents=True)  # (a folder where the log should be)
    result = run(tmp_path)
    assert result.code == 0 and (result.out / "sources-check.last-run").is_file()


# ---- a host that refuses, and the sources a run leaves out -----------------------------------------------------------------------------------------------------


def hosts_asked(result, host: str) -> list[str]:
    return [url for url in result.transport.urls if urllib.parse.urlsplit(url).netloc == host]


def test_eql_tools_refusing_the_first_file_is_not_asked_for_the_second(tmp_path):
    result = run(tmp_path, net=Net(gear=reply(403)))
    assert result.code == 0
    assert hosts_asked(result, TOOLS) == [f"https://{TOOLS}/robots.txt", sc.GEAR_URL]
    text = report(result)
    assert "- gear: unreachable (HTTP 403)" in text
    assert "- quests: unreachable (HTTP 403 earlier in this run; the host is not asked again)" in text
    assert summary(text) == "4 catalog titles changed; EQL Tools: gear unreachable, quests unreachable; patch notes recorded; 2 unreachable"
    assert (result.out / "sources-check.last-run").is_file()


def test_the_wiki_refusing_a_page_of_the_changes_is_not_asked_for_the_patch_notes(tmp_path):
    result = run(tmp_path, net=Net(changes_2=reply(429, b"", {"Retry-After": "3600"})))
    assert len(hosts_asked(result, WIKI)) == 3  # (robots.txt and the two pages of changes: not the patch notes)
    text = report(result)
    assert "- wiki changes: unreachable (HTTP 429)" in text
    assert "- patch notes: unreachable (HTTP 429 earlier in this run; the host is not asked again)" in text
    assert "gear recorded, quests recorded" in text  # (another host, asked as usual)


def test_a_source_that_is_left_out_is_not_asked_for_and_its_record_stays(tmp_path):
    run(tmp_path)
    before = state(SimpleNamespace(out=tmp_path / "checks"))
    result = run(tmp_path, "--skip", "eqltools", now=NOW + 7 * DAY)
    assert result.code == 0 and hosts_asked(result, TOOLS) == []
    text = report(result)
    assert f"- gear: skipped (--skip eqltools); the record of the last run (sha256 `{GEAR}`) stays" in text
    assert f"- quests: skipped (--skip eqltools); the record of the last run (sha256 `{QUESTS}`) stays" in text
    assert summary(text) == "4 catalog titles changed; EQL Tools: gear skipped, quests skipped; patch notes unchanged; 0 unreachable"
    assert state(result)["eqltools"] == before["eqltools"] and (result.out / "sources-check.last-run").is_file()


def test_leaving_out_the_wiki_changes_asks_for_none_and_the_next_run_reads_from_where_the_last_one_that_read_them_stopped(tmp_path):
    run(tmp_path)
    skipped = run(tmp_path, "--skip", "wiki", now=NOW + 7 * DAY)
    assert changes_requests(skipped) == [] and len(hosts_asked(skipped, WIKI)) == 2  # (robots.txt and the patch notes)
    text = report(skipped)
    assert "- wiki changes: skipped (--skip wiki); the next run reads from the time of the last run that read them" in text
    assert summary(text).startswith("wiki changes skipped; EQL Tools: gear unchanged")
    assert state(skipped)["recent_changes"] == {"checked_until": "2026-10-18T10:00:03Z"}
    third = run(tmp_path, now=NOW + 14 * DAY)
    assert changes_requests(third)[0]["rcstart"] == "2026-10-18T09:50:03Z"  # (ten minutes before the end of the last window that read them)


def test_leaving_out_the_patch_notes_asks_for_none_and_keeps_their_record(tmp_path):
    run(tmp_path)
    before = state(SimpleNamespace(out=tmp_path / "checks"))
    result = run(tmp_path, "--skip", "patch-notes", now=NOW + 7 * DAY)
    assert not [url for url in result.transport.urls if "prop=revisions" in url]
    text = report(result)
    assert f"- patch notes: skipped (--skip patch-notes); the record of the last run (sha256 `{PATCH}`) stays" in text
    assert "patch notes skipped; 0 unreachable" in summary(text) and state(result)["patch_notes"] == before["patch_notes"]


def test_two_sources_can_be_left_out_at_once_and_the_options_can_be_repeated_or_given_with_an_equals_sign(tmp_path):
    result = run(tmp_path, "--skip", "wiki", "--skip=eqltools")
    assert changes_requests(result) == [] and hosts_asked(result, TOOLS) == []
    assert summary(report(result)) == "wiki changes skipped; EQL Tools: gear skipped, quests skipped; patch notes recorded; 0 unreachable"


def test_a_run_that_leaves_out_every_source_is_refused_because_its_stamp_would_say_nothing(tmp_path, capsys):
    result = run(tmp_path, "--skip", "wiki", "--skip", "eqltools", "--skip", "patch-notes")
    err = capsys.readouterr().err
    assert result.code == 2 and err.startswith("sources-check: --skip") and "every source" in err and len(err.splitlines()) == 1
    assert result.transport.calls == [] and not (result.out / "sources-check.last-run").exists()


def test_a_source_that_does_not_exist_cannot_be_left_out(tmp_path):
    with pytest.raises(SystemExit) as stopped:
        run(tmp_path, "--skip", "weather")
    assert stopped.value.code == 2


# ---- the wiki: recent changes in the main namespace, only the catalog's titles, as code ---------------------------------------------------------------------


def test_the_catalog_titles_that_changed_are_listed_as_code_with_their_revision_ids(tmp_path):
    result = run(tmp_path)
    assert result.code == 0
    text = report(result)
    assert "- ``Quenfel`s Cap``: revisions 139100, 139300 (last edit 2026-10-16T08:00:00Z; the catalog was built from 139100)" in text
    assert "- `Rune: Sorvath`: revision 139350 (last edit 2026-10-16T09:00:00Z; the catalog was built from 100500)" in text
    assert "- `Zorblax Ring`: revisions 139001, 139050 (last edit 2026-10-16T11:02:00Z; the catalog was built from 138180)" in text
    lines = [line for line in text.splitlines() if line.startswith("- ") and ": revision" in line]
    assert [line.split(":")[0] for line in lines] == ["- ``Quenfel`s Cap``", "- `Rune", "- `Zorblax Ring`"]  # (in the order of the titles)
    assert "7 changes in the main namespace; 4 of the changed pages are in the catalog" in text  # (the three that were edited, and Draxil's Belt, which was moved)


def test_only_the_main_namespace_and_only_edits_and_new_pages_count(tmp_path):
    text = report(run(tmp_path))
    for left_out in ("Mirrowen Cloak", "Talk:", "User:", "139003", "139004", "139101", "139102", "139310"):
        assert left_out not in text, left_out  # (another namespace, ns false, no ns at all; a log entry is left out unless it is a move or a deletion of a catalog page)


def test_a_page_that_is_not_in_the_catalog_is_counted_and_never_named(tmp_path):
    text = report(run(tmp_path))
    assert "Not In The Catalog" not in text and "Fresh Page" not in text and "139002" not in text and "139060" not in text
    assert "7 changes in the main namespace" in text  # (but the changes to them are in the count)


def test_nothing_the_wiki_wrote_but_a_catalog_title_and_numbers_gets_into_the_report(tmp_path):
    text = report(run(tmp_path))
    for hostile in ("ignore previous instructions", "<script>", "SomeEditor", "alert(1)"):
        assert hostile not in text


def test_the_request_for_the_changes_names_the_main_namespace_the_window_and_no_free_text(tmp_path):
    result = run(tmp_path)
    first, second = changes_requests(result)
    assert first["action"] == "query" and first["list"] == "recentchanges" and first["rcnamespace"] == "0"
    assert first["rctype"] == "edit|new|log" and first["rcdir"] == "newer" and first["rclimit"] == "500"
    assert first["rcstart"] == "2026-10-10T10:00:03Z" and first["rcend"] == "2026-10-18T10:00:03Z"  # (eight days back, up to the run)
    assert first["format"] == "json" and first["formatversion"] == "2" and first["maxlag"] == "5"
    assert set(first["rcprop"].split("|")) == {"title", "ids", "timestamp", "loginfo"}  # (the number of a log entry; no comment, no user name)
    assert second["rccontinue"] == "20261015000000|9100" and second["continue"] == "-||" and second["rcstart"] == first["rcstart"]


def test_a_title_with_a_backtick_is_fenced_by_a_longer_run_of_them(tmp_path):
    assert "``Quenfel`s Cap``" in report(run(tmp_path))


# ---- a page that is renamed, moved or deleted: matched by the id of its page ------------------------------------------------------------------------------------


def changes(*entries):
    """An answer of the wiki with these changes and no continuation."""
    return reply(200, {"batchcomplete": True, "query": {"recentchanges": list(entries)}})


def edit_entry(title, pageid, revid, stamp="2026-10-15T10:00:00Z", ns=0, kind="edit"):
    entry = {"type": kind, "ns": ns, "title": title, "revid": revid, "old_revid": revid - 1, "rcid": revid + 1000, "timestamp": stamp}
    if pageid is not None:
        entry["pageid"] = pageid
    return entry


def log_entry(title, pageid, logtype, logaction, logid, stamp="2026-10-15T11:00:00Z", ns=0, rcid=None):
    entry = {"type": "log", "ns": ns, "title": title, "pageid": pageid, "revid": 0, "old_revid": 0, "timestamp": stamp, "logtype": logtype, "logaction": logaction}
    if logid is not None:
        entry["logid"] = logid
    if rcid is not None:
        entry["rcid"] = rcid
    return entry


def page_lines(result) -> list[str]:
    return [line for line in report(result).splitlines() if line.startswith("- `")]


def test_a_move_of_a_catalog_page_is_reported_by_the_catalog_title_and_the_number_of_the_log_entry(tmp_path):
    text = report(run(tmp_path))
    assert "- `Draxil's Belt`: moved on the wiki (log entry 9005, 2026-10-12T09:19:00Z); the catalog was built from 130500" in text


def test_an_edit_made_after_a_move_is_seen_under_the_catalog_title_and_the_new_title_is_not_shown(tmp_path):
    net = Net(changes_1=changes(edit_entry("A Grander Name For The Belt", 104, 139200)))
    result = run(tmp_path, net=net)
    assert page_lines(result) == ["- `Draxil's Belt`: revision 139200 (last edit 2026-10-15T10:00:00Z; the catalog was built from 130500)"]
    assert "Grander" not in report(result)
    assert "1 change in the main namespace; 1 of the changed pages is in the catalog" in report(result)


def test_another_page_that_now_has_the_title_of_a_catalog_page_is_not_that_page(tmp_path):
    result = run(tmp_path, net=Net(changes_1=changes(edit_entry("Zorblax Ring", 777, 140000))))
    assert page_lines(result) == [] and "1 change in the main namespace; none of the changed pages is in the catalog." in report(result)


def test_a_deletion_is_reported_by_the_title_because_the_page_id_of_a_deleted_page_is_gone(tmp_path):
    entry = log_entry("Mirrowen Cloak", 0, "delete", "delete", 7001)
    result = run(tmp_path, net=Net(changes_1=changes(entry)))
    assert page_lines(result) == ["- `Mirrowen Cloak`: deleted on the wiki (log entry 7001, 2026-10-15T11:00:00Z); the catalog was built from 120000"]
    assert "0 changes in the main namespace; 1 of the changed pages is in the catalog" in report(result)


def test_a_move_is_reported_whether_the_entry_names_the_old_page_by_its_id_or_only_by_its_title(tmp_path):
    for pageid in (104, 4242, 0, None):  # (4242: the page of the redirect that the move left behind)
        entry = log_entry("Draxil's Belt", pageid, "move", "move", 7002)
        result = run(tmp_path / str(pageid), net=Net(changes_1=changes(entry)))
        assert page_lines(result) == ["- `Draxil's Belt`: moved on the wiki (log entry 7002, 2026-10-15T11:00:00Z); the catalog was built from 130500"], pageid


def test_a_page_that_was_edited_and_moved_is_one_line_that_says_both(tmp_path):
    entries = [edit_entry("Draxil's Belt", 104, 139200, "2026-10-15T10:00:00Z"), log_entry("Draxil's Belt", 104, "move", "move", 7003, "2026-10-15T12:00:00Z")]
    result = run(tmp_path, net=Net(changes_1=changes(*entries)))
    assert page_lines(result) == [
        "- `Draxil's Belt`: moved on the wiki (log entry 7003, 2026-10-15T12:00:00Z); revision 139200 (last edit 2026-10-15T10:00:00Z; the catalog was built from 130500)"
    ]


def test_a_move_and_then_a_deletion_of_one_page_are_both_said_in_the_order_they_happened(tmp_path):
    entries = [log_entry("Draxil's Belt", 104, "delete", "delete", 7005, "2026-10-15T13:00:00Z"), log_entry("Draxil's Belt", 104, "move", "move", 7004, "2026-10-15T12:00:00Z")]
    (line,) = page_lines(run(tmp_path, net=Net(changes_1=changes(*entries))))
    assert line == (
        "- `Draxil's Belt`: moved on the wiki (log entry 7004, 2026-10-15T12:00:00Z), deleted on the wiki (log entry 7005, 2026-10-15T13:00:00Z); the catalog was built from 130500"
    )


@pytest.mark.parametrize(
    "entry",
    [
        log_entry("Zorblax Ring", 101, "patrol", "patrol", 7010),
        log_entry("Zorblax Ring", 101, "upload", "upload", 7011),
        log_entry("Zorblax Ring", 101, "protect", "protect", 7012),
        log_entry("Zorblax Ring", 101, "delete", "revision", 7013),
        log_entry("Zorblax Ring", 101, "delete", "restore", 7014),
        log_entry("Zorblax Ring", 101, "newusers", "create", 7015),
        log_entry("Zorblax Ring", 101, "move", "move", 7016, ns=1),  # (another namespace)
        log_entry("Zorblax Ring", 101, "move", "move", None),  # (no number to say)
        log_entry("Not In The Catalog", 900, "move", "move", 7017),
        log_entry("Not In The Catalog", 900, "delete", "delete", 7018),
    ],
)
def test_a_log_entry_that_is_not_a_move_or_a_deletion_of_a_catalog_page_in_the_main_namespace_is_left_out(tmp_path, entry):
    result = run(tmp_path, net=Net(changes_1=changes(entry)))
    assert page_lines(result) == [] and "0 changes in the main namespace; none of the changed pages is in the catalog." in report(result)
    assert "Not In The Catalog" not in report(result)


def test_the_rcid_names_a_log_entry_that_has_no_log_number(tmp_path):
    entry = log_entry("Draxil's Belt", 104, "move", "move", None, rcid=9999)
    (line,) = page_lines(run(tmp_path, net=Net(changes_1=changes(entry))))
    assert "(log entry 9999," in line


def test_a_log_entry_that_comes_twice_is_one_event(tmp_path):
    entry = log_entry("Draxil's Belt", 104, "move", "move", 7020)
    (line,) = page_lines(run(tmp_path, net=Net(changes_1=changes(entry, entry))))
    assert line.count("log entry") == 1


def test_a_change_with_no_page_id_is_matched_by_its_title(tmp_path):
    result = run(tmp_path, net=Net(changes_1=changes(edit_entry("Zorblax Ring", None, 140001))))
    assert page_lines(result) == ["- `Zorblax Ring`: revision 140001 (last edit 2026-10-15T10:00:00Z; the catalog was built from 138180)"]


def test_the_request_asks_for_the_move_and_deletion_log_entries_too(tmp_path):
    first = changes_requests(run(tmp_path))[0]
    assert first["rctype"] == "edit|new|log" and first["rcnamespace"] == "0"
    assert set(first["rcprop"].split("|")) == {"title", "ids", "timestamp", "loginfo"}  # (still no comment and no user name)


def test_the_second_page_of_changes_is_asked_for_and_a_repeated_token_is_unreachable(tmp_path):
    again = json.loads(fixture("recentchanges-1.json"))
    net = Net(changes_2=reply(200, again))  # the second page gives the token of the first again
    result = run(tmp_path, net=net)
    assert "unreachable (the wiki repeated a continuation token)" in report(result)
    assert "Zorblax Ring" not in report(result)


def test_a_wiki_that_never_stops_continuing_is_unreachable_after_a_number_of_pages(tmp_path):
    counter = iter(range(10_000))

    def endless(url, headers):
        if route(url) in ("changes-1", "changes-2"):
            return reply(200, {"query": {"recentchanges": []}, "continue": {"rccontinue": f"t|{next(counter)}", "continue": "-||"}})
        return Net()(url, headers)

    result = run(tmp_path, net=endless)
    assert f"more than {sc.MAX_PAGES} pages of changes" in report(result)
    assert len(changes_requests(result)) == sc.MAX_PAGES


# ---- a window with more changes than a run reads: partial, and the next run goes on ----------------------------------------------------------------------------

LONG_START = datetime.datetime(2026, 10, 18, 7, 0, 0, tzinfo=datetime.timezone.utc)


class LongWiki:
    """A wiki with a change of a catalog page every minute from 07:00, which keeps to the window it is asked for and gives five changes at a time."""

    def __init__(self, count: int) -> None:
        self.entries = [edit_entry("Zorblax Ring", 101, 150000 + n, common.utc_text(LONG_START + datetime.timedelta(minutes=n))) for n in range(count)]

    def __call__(self, url, headers):
        if route(url) not in ("changes-1", "changes-2"):
            return Net()(url, headers)
        asked = query_of(url)
        chosen = [entry for entry in self.entries if asked["rcstart"] <= entry["timestamp"] <= asked["rcend"]]
        offset = int(asked.get("rccontinue", "0"))
        page = chosen[offset : offset + 5]
        answer = {"batchcomplete": True, "query": {"recentchanges": page}}
        if offset + 5 < len(chosen):
            answer["continue"] = {"rccontinue": str(offset + 5), "continue": "-||"}
        return reply(200, answer)


@pytest.fixture
def small_pages(monkeypatch):
    monkeypatch.setattr(sc, "MAX_PAGES", 3)
    monkeypatch.setattr(sc, "CHANGES_PER_PAGE", 5)


def revisions_listed(result) -> list[int]:
    found = []
    for line in page_lines(result):
        match = re.search(r"revisions? ([0-9, ]+?)(?: \(|$)", line)
        if match:
            found += [int(number) for number in match.group(1).split(", ")]
    return found


def test_a_window_with_more_changes_than_a_run_reads_is_partial_and_says_where_it_stopped(tmp_path, small_pages):
    result = run(tmp_path, net=LongWiki(40))
    text = report(result)
    assert result.code == 0 and len(changes_requests(result)) == 3
    assert "15 changes in the main namespace; 1 of the changed pages is in the catalog" in text
    assert revisions_listed(result) == [150000 + n for n in range(15)]
    assert "the list is partial" in text and "read them up to 2026-10-18T07:14:00Z" in text and "the next run goes on from there" in text
    assert "partial" in summary(text) and (result.out / "sources-check.last-run").is_file()
    assert state(result)["recent_changes"] == {"checked_until": "2026-10-18T07:14:00Z", "partial": True, "seen": ["r150014"]}  # (the window moves to the last change read)


def test_the_next_run_goes_on_from_the_last_change_read_and_every_change_is_listed_once(tmp_path, small_pages):
    wiki = LongWiki(40)
    listed: list[int] = []
    for number in range(10):
        result = run(tmp_path, net=wiki, now=NOW + datetime.timedelta(hours=number))
        listed += revisions_listed(result)
        if number == 1:
            assert changes_requests(result)[0]["rcstart"] == "2026-10-18T07:14:00Z"  # (where the last run stopped, with no overlap: that time is the wiki's own)
            assert "(the previous run, which stopped early because its list was partial)" in report(result)
        if "partial" not in summary(report(result)):
            break
    else:
        pytest.fail("the changes were never all read")
    assert sorted(listed) == [150000 + n for n in range(40)]  # (each once)
    assert "recent_changes" in state(result) and "partial" not in state(result)["recent_changes"]
    assert state(result)["recent_changes"]["checked_until"] == common.utc_text(NOW + datetime.timedelta(hours=number))  # (and the window is the run's again)


def test_a_window_with_exactly_as_many_changes_as_a_run_reads_is_not_partial(tmp_path, small_pages):
    result = run(tmp_path, net=LongWiki(15))
    assert "partial" not in report(result) and revisions_listed(result) == [150000 + n for n in range(15)]
    assert state(result)["recent_changes"] == {"checked_until": "2026-10-18T10:00:03Z"}  # (the window is the run's, and nothing in its last ten minutes to remember)


def test_a_list_that_is_partial_and_a_wiki_that_gives_no_change_while_it_goes_on_for_ever_are_not_the_same(tmp_path, small_pages):
    counter = iter(range(10_000))

    def endless(url, headers):
        if route(url) in ("changes-1", "changes-2"):
            return reply(200, {"query": {"recentchanges": []}, "continue": {"rccontinue": f"t|{next(counter)}", "continue": "-||"}})
        return Net()(url, headers)

    result = run(tmp_path, net=endless)
    assert "the list is partial" not in report(result) and "unreachable (more than 3 pages of changes)" in report(result)


@pytest.mark.parametrize("partial", [5, "yes", None, [True]])
def test_a_partial_flag_that_is_not_a_boolean_is_a_damaged_record_and_the_time_is_still_believed(tmp_path, partial):
    out = tmp_path / "checks"
    out.mkdir()
    document = {"version": 1, "recent_changes": {"checked_until": "2026-10-18T10:00:03Z", "partial": partial}}
    (out / "sources-check.state.json").write_text(json.dumps(document), encoding="utf-8")
    result = run(tmp_path, now=NOW + 7 * DAY)
    assert "no usable record of the previous run" in report(result)
    assert changes_requests(result)[0]["rcstart"] == "2026-10-18T09:50:03Z"


def test_a_catalog_title_that_changed_twice_is_one_line_and_a_revision_is_counted_once(tmp_path):
    text = report(run(tmp_path))
    assert text.count("`Zorblax Ring`") == 1 and text.count("139050") == 1


# ---- the window --------------------------------------------------------------------------------------------------------------------------------------


def test_the_window_starts_ten_minutes_before_where_the_previous_run_looked_up_to(tmp_path):
    run(tmp_path)
    later = NOW + 7 * DAY + datetime.timedelta(minutes=5)
    second = run(tmp_path, now=later)
    first = changes_requests(second)[0]
    assert first["rcstart"] == "2026-10-18T09:50:03Z" and first["rcend"] == common.utc_text(later)
    assert "since 2026-10-18T09:50:03Z (the previous run, less 10 minutes" in report(second)


def honest_wiki(entries):
    """A wiki that keeps to the window it is asked for: the changes from rcstart to rcend, oldest first, in one page."""

    def handler(url, headers):
        if route(url) in ("changes-1", "changes-2"):
            asked = query_of(url)
            chosen = sorted((e for e in entries if asked["rcstart"] <= e["timestamp"] <= asked["rcend"]), key=lambda e: (e["timestamp"], e.get("revid", 0)))
            return changes(*chosen)
        return Net()(url, headers)

    return handler


def test_a_change_that_reached_the_list_late_is_listed_by_the_next_run(tmp_path):
    late = edit_entry("Zorblax Ring", 101, 140005, "2026-10-18T09:58:00Z")  # (made before the last run ended, and in the list only after: the clocks differ, and so do the servers)
    run(tmp_path, net=honest_wiki([]))
    second = run(tmp_path, net=honest_wiki([late]), now=NOW + datetime.timedelta(hours=1))
    assert page_lines(second) == ["- `Zorblax Ring`: revision 140005 (last edit 2026-10-18T09:58:00Z; the catalog was built from 138180)"]


def test_a_change_in_the_overlap_is_listed_once_across_two_runs_and_the_record_holds_only_what_the_next_window_can_hold(tmp_path):
    before = edit_entry("Zorblax Ring", 101, 140000, "2026-10-18T09:30:00Z")
    inside = edit_entry("Zorblax Ring", 101, 140001, "2026-10-18T09:55:00Z")  # (in the last ten minutes before the end of the window)
    first = run(tmp_path, net=honest_wiki([before, inside]))
    assert page_lines(first) == ["- `Zorblax Ring`: revisions 140000, 140001 (last edit 2026-10-18T09:55:00Z; the catalog was built from 138180)"]
    assert state(first)["recent_changes"] == {"checked_until": "2026-10-18T10:00:03Z", "seen": ["r140001"]}
    new = edit_entry("Zorblax Ring", 101, 140002, "2026-10-18T10:30:00Z")
    second = run(tmp_path, net=honest_wiki([before, inside, new]), now=NOW + datetime.timedelta(hours=1))
    assert changes_requests(second)[0]["rcstart"] == "2026-10-18T09:50:03Z"
    assert page_lines(second) == ["- `Zorblax Ring`: revision 140002 (last edit 2026-10-18T10:30:00Z; the catalog was built from 138180)"]
    assert "1 change in the main namespace; 1 of the changed pages is in the catalog" in report(second)
    assert state(second)["recent_changes"] == {"checked_until": "2026-10-18T11:00:03Z"}  # (nothing in the last ten minutes: nothing to remember)


def test_a_change_of_a_page_that_is_not_in_the_catalog_is_counted_once_across_two_runs_too(tmp_path):
    other = edit_entry("Not In The Catalog", 900, 140010, "2026-10-18T09:59:00Z")
    first = run(tmp_path, net=honest_wiki([other]))
    assert "1 change in the main namespace; none of the changed pages is in the catalog." in report(first)
    second = run(tmp_path, net=honest_wiki([other]), now=NOW + datetime.timedelta(hours=1))
    assert "0 changes in the main namespace; none of the changed pages is in the catalog." in report(second)


def test_a_move_in_the_overlap_is_listed_once_across_two_runs(tmp_path):
    move = log_entry("Draxil's Belt", 104, "move", "move", 7100, "2026-10-18T09:58:00Z")
    first = run(tmp_path, net=honest_wiki([move]))
    assert page_lines(first) == ["- `Draxil's Belt`: moved on the wiki (log entry 7100, 2026-10-18T09:58:00Z); the catalog was built from 130500"]
    assert state(first)["recent_changes"]["seen"] == ["l7100"]
    second = run(tmp_path, net=honest_wiki([move]), now=NOW + datetime.timedelta(hours=1))
    assert page_lines(second) == []


def test_a_wiki_that_could_not_be_read_or_was_left_out_keeps_the_record_of_what_was_seen(tmp_path):
    inside = edit_entry("Zorblax Ring", 101, 140001, "2026-10-18T09:55:00Z")
    first = run(tmp_path, net=honest_wiki([inside]))
    kept = state(first)["recent_changes"]
    assert kept == {"checked_until": "2026-10-18T10:00:03Z", "seen": ["r140001"]}
    failed = run(tmp_path, net=Net(changes_1=reply(500)), now=NOW + datetime.timedelta(hours=1))
    assert state(failed)["recent_changes"] == kept
    skipped = run(tmp_path, "--skip", "wiki", now=NOW + datetime.timedelta(hours=2))
    assert state(skipped)["recent_changes"] == kept
    third = run(tmp_path, net=honest_wiki([inside]), now=NOW + datetime.timedelta(hours=3))
    assert page_lines(third) == []  # (still the same change, still not listed twice)


@pytest.mark.parametrize("seen", [5, "r1", {"a": 1}, ["r1", 2], ["x9"], ["r1", "r"], [""], ["r-1"], ["r1.5"]])
def test_a_list_of_what_was_seen_that_is_not_one_is_a_damaged_record_and_the_time_is_still_believed(tmp_path, seen):
    out = tmp_path / "checks"
    out.mkdir()
    document = {"version": 1, "recent_changes": {"checked_until": "2026-10-18T10:00:03Z", "seen": seen}}
    (out / "sources-check.state.json").write_text(json.dumps(document), encoding="utf-8")
    result = run(tmp_path, now=NOW + 7 * DAY)
    assert "no usable record of the previous run" in report(result)
    assert changes_requests(result)[0]["rcstart"] == "2026-10-18T09:50:03Z"


def test_without_a_previous_run_the_window_is_eight_days_back_or_as_many_as_asked(tmp_path):
    assert changes_requests(run(tmp_path))[0]["rcstart"] == "2026-10-10T10:00:03Z"
    assert "(8 days back; there is no earlier run)" in report(run(tmp_path / "other"))
    assert changes_requests(run(tmp_path / "third", "--days", "3"))[0]["rcstart"] == "2026-10-15T10:00:03Z"


def test_a_state_that_cannot_be_read_is_taken_as_no_state_and_the_report_says_so(tmp_path):
    out = tmp_path / "checks"
    out.mkdir()
    for text in ("{not json", "[]", '{"recent_changes": 5}', '{"recent_changes": {"checked_until": "yesterday"}}'):
        (out / "sources-check.state.json").write_text(text, encoding="utf-8")
        result = run(tmp_path)
        assert changes_requests(result)[0]["rcstart"] == "2026-10-10T10:00:03Z", text
        assert "no usable record of the previous run" in report(result), text


def test_a_state_that_looks_up_to_a_time_after_the_run_is_not_believed(tmp_path):
    run(tmp_path, now=NOW + 30 * DAY)  # (a clock that was wrong)
    result = run(tmp_path)
    assert changes_requests(result)[0]["rcstart"] == "2026-10-10T10:00:03Z"
    assert "no usable record of the previous run" in report(result)


def test_a_window_older_than_the_wiki_keeps_its_changes_is_said_in_the_report(tmp_path):
    run(tmp_path, now=NOW - 100 * DAY)
    text = report(run(tmp_path))
    assert "keeps its recent changes for about 90 days" in text
    quiet = report(run(tmp_path / "quiet"))
    assert "keeps its recent changes" not in quiet


# ---- EQL Tools and the patch notes: the hashes ----------------------------------------------------------------------------------------------------------


def test_the_first_run_records_the_hashes_and_calls_nothing_changed(tmp_path):
    result = run(tmp_path)
    text = report(result)
    assert f"- gear: recorded (sha256 `{GEAR}`, {len(fixture('gear.json'))} bytes)" in text
    assert f"- quests: recorded (sha256 `{QUESTS}`, {len(fixture('quests.json'))} bytes)" in text
    assert f"- patch notes: recorded (revision 150100, sha256 `{PATCH}`)" in text
    saved = state(result)
    assert saved["eqltools"]["gear"]["sha256"] == GEAR and saved["eqltools"]["quests"]["sha256"] == QUESTS
    assert saved["patch_notes"] == {"sha256": PATCH, "revid": 150100}
    assert saved["recent_changes"]["checked_until"] == "2026-10-18T10:00:03Z"


def test_a_file_with_the_same_hash_is_unchanged_and_one_with_another_is_changed(tmp_path):
    run(tmp_path)
    same = run(tmp_path)
    text = report(same)
    assert f"- gear: unchanged (sha256 `{GEAR}`)" in text and f"- quests: unchanged (sha256 `{QUESTS}`)" in text
    changed_gear = b'{"meta": {"license": "CC BY-SA 4.0"}, "items": {"zorblax ring": {"n": "Zorblax Ring", "sl": ["FINGER"]}}}'
    third = run(tmp_path, net=Net(gear=reply(200, changed_gear)))
    text = report(third)
    assert f"- gear: changed (sha256 `{sha256(changed_gear)}`, it was `{GEAR}`; {len(changed_gear)} bytes)" in text
    assert f"- quests: unchanged" in text
    assert state(third)["eqltools"]["gear"]["sha256"] == sha256(changed_gear)  # (the next run compares with this one)


def test_the_hash_of_a_file_is_that_of_the_unpacked_bytes(tmp_path):
    result = run(tmp_path, net=Net(gear=reply(200, fixture("gear.json"), gz=True)))
    assert f"- gear: recorded (sha256 `{GEAR}`" in report(result)


def test_the_patch_notes_are_changed_when_their_text_is_and_the_report_says_which_revision(tmp_path):
    run(tmp_path)
    document = json.loads(fixture("patch-notes.json"))
    revision = document["query"]["pages"][0]["revisions"][0]
    revision["revid"] = 150200
    revision["slots"]["main"]["content"] += "* A line added since.\n"
    new_hash = sha256(revision["slots"]["main"]["content"].encode("utf-8"))
    text = report(run(tmp_path, net=Net(patch_notes=reply(200, document))))
    assert f"- patch notes: changed (revision 150200, it was 150100; sha256 `{new_hash}`, it was `{PATCH}`)" in text


def test_the_patch_notes_request_names_the_page_and_asks_for_the_text(tmp_path):
    result = run(tmp_path)
    (asked,) = [query_of(url) for url in result.transport.urls if "prop=revisions" in url]
    assert asked["titles"] == "Patch Notes" and asked["rvprop"] == "ids|timestamp|content" and asked["rvslots"] == "main"
    assert asked["format"] == "json" and asked["formatversion"] == "2" and asked["maxlag"] == "5"


def test_the_two_eqltools_files_are_asked_for_by_their_addresses(tmp_path):
    result = run(tmp_path)
    assert sc.GEAR_URL == "https://eqltools.com/gear/data/gear-data.json" and sc.QUESTS_URL == "https://eqltools.com/companion/data/quest-items.json"
    assert [url for url in result.transport.urls if urllib.parse.urlsplit(url).netloc == TOOLS and not url.endswith("/robots.txt")] == [sc.GEAR_URL, sc.QUESTS_URL]


# ---- unreachable is never changed ---------------------------------------------------------------------------------------------------------------------

FAILURES = {
    "a 500": reply(500, "Internal Server Error"),
    "a 503": reply(503, "", {"Retry-After": "120"}),
    "a 404": reply(404, "<html>no such file</html>"),
    "a redirect": reply(302, "", {"Location": "https://elsewhere.invalid/"}),
    "html where json is expected": reply(200, "<html><body>Down for maintenance</body></html>", {"Content-Type": "text/html"}),
    "an empty answer": reply(200, ""),
    "a timeout": TimeoutError("slow"),
    "a reset": ConnectionResetError("reset"),
}
SOURCES = ["changes-1", "changes-2", "patch-notes", "gear", "quests"]


@pytest.mark.parametrize("failure", list(FAILURES))
@pytest.mark.parametrize("source", SOURCES)
def test_a_source_that_cannot_be_read_is_unreachable_and_never_changed(tmp_path, source, failure):
    run(tmp_path)  # a good run before: its records are what the bad one must leave alone
    before = state(SimpleNamespace(out=tmp_path / "checks"))
    now = NOW + 7 * DAY
    result = run(tmp_path, net=Net(**{source: FAILURES[failure]}), now=now)
    assert result.code == 0  # (the run finished)
    text = report(result)
    assert summary(text).endswith("; 1 unreachable")
    assert "- gear: changed" not in text and "- quests: changed" not in text and "- patch notes: changed" not in text
    expected = json.loads(json.dumps(before))
    wiki = source in ("changes-1", "changes-2")
    if wiki:
        assert "wiki changes unreachable" in summary(text) and "`Zorblax Ring`" not in text  # (half a list is not shown)
    else:
        expected["recent_changes"]["checked_until"] = common.utc_text(now)  # (the window moves on when the wiki was read)
    assert state(result) == expected  # (a source that was not read keeps its record, the others are recorded again)


def wiki_line(result) -> str:
    (line,) = [line for line in report(result).splitlines() if line.startswith("- wiki changes: unreachable")]
    return line


def test_an_unreachable_wiki_on_a_first_run_says_that_the_next_run_reads_the_window_of_a_first_run_not_from_the_same_time(tmp_path):
    line = wiki_line(run(tmp_path, net=Net(changes_1=reply(500))))
    assert "from the same time" not in line
    assert line.endswith("nothing is known of the changes in this window, and there is no earlier time to go on from, so the next run reads 8 days back, as a first run does")
    assert wiki_line(run(tmp_path / "three", "--days", "3", net=Net(changes_1=reply(500)))).endswith("so the next run reads 3 days back, as a first run does")
    one = wiki_line(run(tmp_path / "one", "--days", "1", net=Net(changes_1=reply(500))))
    assert one.endswith("so the next run reads 1 day back, as a first run does")
    assert "recent_changes" not in state(run(tmp_path / "again", net=Net(changes_1=reply(500))))  # (and that is what the record says: there is no time to go on from)


def test_an_unreachable_wiki_after_a_run_that_read_it_says_the_time_the_next_run_goes_on_from(tmp_path):
    run(tmp_path)
    line = wiki_line(run(tmp_path, net=Net(changes_1=reply(500)), now=NOW + 7 * DAY))
    assert line.endswith("and the next run asks again from the time of the last run that read them, 2026-10-18T10:00:03Z, less 10 minutes")


def test_an_unreachable_wiki_after_a_partial_run_says_that_the_next_run_goes_on_from_where_that_one_stopped(tmp_path, small_pages):
    run(tmp_path, net=LongWiki(40))
    line = wiki_line(run(tmp_path, net=Net(changes_1=reply(500)), now=NOW + 7 * DAY))
    assert line.endswith("and the next run goes on from where the last one that read them stopped, 2026-10-18T07:14:00Z")


def read_to_the_end(tmp_path, wiki, first_run_number=0):
    """Runs on after the ones already made, one an hour, until a list is not partial; returns the revisions they listed."""
    listed: list[int] = []
    for number in range(first_run_number, first_run_number + 12):
        result = run(tmp_path, net=wiki, now=NOW + datetime.timedelta(hours=number))
        listed += revisions_listed(result)
        if "partial" not in summary(report(result)):
            return listed
    pytest.fail("the changes were never all read")


@pytest.mark.parametrize("how", ["unreachable", "skipped"])
def test_a_wiki_that_is_unreachable_or_left_out_after_a_partial_run_keeps_the_record_of_it_and_the_next_run_starts_where_that_one_stopped(tmp_path, small_pages, how):
    wiki = LongWiki(40)
    first = run(tmp_path, net=wiki)
    kept = state(first)["recent_changes"]
    assert kept == {"checked_until": "2026-10-18T07:14:00Z", "partial": True, "seen": ["r150014"]}
    if how == "unreachable":
        between = run(tmp_path, net=Net(changes_1=reply(500)), now=NOW + datetime.timedelta(hours=1))
    else:
        between = run(tmp_path, "--skip", "wiki", now=NOW + datetime.timedelta(hours=1))
    assert state(between)["recent_changes"] == kept  # (the whole record: the flag that says the next window begins exactly there, and what was seen at that time)
    third = run(tmp_path, net=wiki, now=NOW + datetime.timedelta(hours=2))
    assert changes_requests(third)[0]["rcstart"] == "2026-10-18T07:14:00Z"  # (not ten minutes earlier: that time is the wiki's own)
    listed = revisions_listed(first) + revisions_listed(third)
    assert len(listed) == len(set(listed)) and 150014 not in revisions_listed(third)  # (the change at the boundary is not listed twice)
    rest = read_to_the_end(tmp_path, wiki, first_run_number=3)
    everything = listed + rest
    assert sorted(everything) == [150000 + n for n in range(40)]  # (and none is lost, nor listed twice, however long the wiki was out of reach)


def test_the_line_of_a_wiki_that_is_left_out_says_what_the_next_run_does_with_the_overlap_and_without_it(tmp_path, small_pages):
    run(tmp_path)
    ordinary = report(run(tmp_path, "--skip", "wiki", now=NOW + 7 * DAY))
    assert "- wiki changes: skipped (--skip wiki); the next run reads from the time of the last run that read them (2026-10-18T10:00:03Z), less 10 minutes" in ordinary
    run(tmp_path / "long", net=LongWiki(40))
    after_partial = report(run(tmp_path / "long", "--skip", "wiki", now=NOW + 7 * DAY))
    assert "(2026-10-18T07:14:00Z), with no overlap, since that list was partial" in after_partial
    (line,) = [line for line in after_partial.splitlines() if line.startswith("- wiki changes: skipped")]
    assert "less 10 minutes" not in line


def test_an_unreachable_wiki_when_the_record_is_damaged_says_that_the_next_run_reads_the_window_of_a_first_run(tmp_path):
    out = tmp_path / "checks"
    out.mkdir()
    (out / "sources-check.state.json").write_text("{not json", encoding="utf-8")
    line = wiki_line(run(tmp_path, net=Net(changes_1=reply(500))))
    assert "so the next run reads 8 days back, as a first run does" in line


def test_what_is_read_is_still_recorded_when_a_neighbour_is_unreachable(tmp_path):
    result = run(tmp_path, net=Net(gear=reply(500)))
    saved = state(result)
    assert "gear" not in saved["eqltools"] and saved["eqltools"]["quests"]["sha256"] == QUESTS and saved["patch_notes"]["sha256"] == PATCH


@pytest.mark.parametrize(
    "answer",
    [reply(200, "[1, 2, 3]"), reply(200, '"text"'), reply(200, "null"), reply(200, "3")],
)
def test_a_json_file_of_eqltools_that_is_not_an_object_is_unreachable(tmp_path, answer):
    text = report(run(tmp_path, net=Net(gear=answer)))
    assert "- gear: unreachable (the answer is not a JSON object)" in text


LICENCE_REASON = "the file does not declare the licence CC BY-SA 4.0"
NOT_THE_FILE = [
    ("a JSON object that is not the file (an error page in JSON)", {"error": "maintenance"}),
    ("a file that declares another licence", {"meta": {"license": "All rights reserved"}, "items": [], "quests": []}),
    ("a file that declares none", {"meta": {}, "items": [], "quests": []}),
    ("a meta that is not an object", {"meta": "CC BY-SA 4.0", "items": [], "quests": []}),
    ("a licence that is not text", {"meta": {"license": 4}, "items": [], "quests": []}),
    ("a licence in another case", {"meta": {"license": "cc by-sa 4.0"}, "items": [], "quests": []}),
]


@pytest.mark.parametrize("file", ["gear", "quests"])
@pytest.mark.parametrize("what, document", NOT_THE_FILE)
def test_a_json_object_that_is_not_the_file_is_unreachable_and_never_changed(tmp_path, file, what, document):
    run(tmp_path)  # a good run before: its records are what the bad answer must leave alone
    before = state(SimpleNamespace(out=tmp_path / "checks"))
    result = run(tmp_path, net=Net(**{file: reply(200, document)}), now=NOW + 7 * DAY)
    text = report(result)
    assert f"- {file}: unreachable ({LICENCE_REASON})" in text and f"- {file}: changed" not in text, what
    assert summary(text).endswith("; 1 unreachable")
    assert state(result)["eqltools"] == before["eqltools"]


@pytest.mark.parametrize(
    "file, key, reason, value",
    [
        ("gear", "items", "the file has no items", None),
        ("gear", "items", "the file has no items", 5),
        ("gear", "items", "the file has no items", "text"),
        ("gear", "items", "the file has no items", True),
        ("quests", "quests", "the file has no list of quests", None),
        ("quests", "quests", "the file has no list of quests", 5),
        ("quests", "quests", "the file has no list of quests", "text"),
        ("quests", "quests", "the file has no list of quests", {"a": 1}),  # (the quests of the real file are a list; its `items` is an object, which is not them)
        ("quests", "quests", "the file has no list of quests", True),
    ],
)
def test_a_file_with_the_licence_but_nothing_of_what_it_holds_is_unreachable(tmp_path, file, key, reason, value):
    document = {"meta": {"license": "CC BY-SA 4.0"}} | ({} if value is None else {key: value})
    text = report(run(tmp_path, net=Net(**{file: reply(200, document)})))
    assert f"- {file}: unreachable ({reason})" in text


GEAR_ITEMS = {"zorblax ring": {"n": "Zorblax Ring", "sl": ["FINGER"]}}


@pytest.mark.parametrize("items", [GEAR_ITEMS, [{"n": "Zorblax Ring", "sl": "FINGER"}], {}, []])
def test_the_gear_file_may_hold_its_items_as_an_object_keyed_by_the_lookup_key_as_the_real_one_does_or_as_a_list(tmp_path, items):
    document = {"meta": {"license": "CC BY-SA 4.0"}, "items": items}
    text = report(run(tmp_path, net=Net(gear=reply(200, document))))
    assert f"- gear: recorded (sha256 `{sha256(json.dumps(document).encode('utf-8'))}`" in text and "unreachable (" not in text and summary(text).endswith("; 0 unreachable")


def test_the_fixtures_are_the_shape_of_the_real_files(tmp_path):
    gear = json.loads(fixture("gear.json"))
    assert isinstance(gear["items"], dict) and all(isinstance(record, dict) and isinstance(record.get("n"), str) for record in gear["items"].values())  # (as the real file: an object)
    quests = json.loads(fixture("quests.json"))
    assert isinstance(quests["quests"], list) and all(isinstance(record, dict) for record in quests["quests"])
    text = report(run(tmp_path))
    assert "- gear: recorded" in text and "- quests: recorded" in text


def real_copies() -> dict[str, Path]:
    """The git-ignored copies of the two real files of EQL Tools, in this checkout or in the main one (a worktree has none of its own)."""
    folders = [REPO / "sources" / "eqltools"]
    try:
        common_dir = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO, capture_output=True, text=True, timeout=30, check=True).stdout.strip()
        folders.append(Path(common_dir).parent / "sources" / "eqltools")
    except (OSError, subprocess.SubprocessError):
        pass
    for folder in folders:
        gear, quests = sorted(folder.glob("gear-data-*.json")), sorted(folder.glob("quest-items-*.json"))
        if gear and quests:
            return {"gear": gear[-1], "quests": quests[-1]}
    return {}


@pytest.mark.skipif(not real_copies(), reason="the git-ignored copies of the two files of EQL Tools are not here")
def test_the_real_files_of_eqltools_are_the_shape_the_check_holds_them_to(tmp_path):
    copies = real_copies()
    result = run(tmp_path, net=Net(gear=reply(200, copies["gear"].read_bytes()), quests=reply(200, copies["quests"].read_bytes())))
    text = report(result)
    assert "- gear: recorded" in text and "- quests: recorded" in text and "unreachable (" not in text and summary(text).endswith("; 0 unreachable")


def test_a_file_at_the_address_of_the_other_one_is_not_the_file(tmp_path):
    result = run(tmp_path, net=Net(gear=reply(200, fixture("quests.json")), quests=reply(200, fixture("gear.json"))))
    text = report(result)
    assert "- gear: unreachable (the file has no items)" in text and "- quests: unreachable (the file has no list of quests)" in text
    assert summary(text).endswith("; 2 unreachable")


@pytest.mark.parametrize("emptied", [b'{"meta": {"license": "CC BY-SA 4.0"}, "items": []}', b'{"meta": {"license": "CC BY-SA 4.0"}, "items": {}}'])
def test_an_empty_list_or_object_in_the_right_file_is_a_change_of_the_file_and_not_an_unreachable_one(tmp_path, emptied):
    run(tmp_path)
    text = report(run(tmp_path, net=Net(gear=reply(200, emptied)), now=NOW + 7 * DAY))
    assert f"- gear: changed (sha256 `{sha256(emptied)}`" in text


def test_the_reason_never_carries_what_the_file_said(tmp_path):
    document = {"meta": {"license": "Buy my pills at https://spam.invalid/"}, "items": []}
    text = report(run(tmp_path, net=Net(gear=reply(200, document))))
    assert "spam.invalid" not in text and "pills" not in text


@pytest.mark.parametrize(
    "answer, reason",
    [
        (reply(200, {"query": {"pages": [{"title": "Patch Notes", "missing": True}]}}), "the page is not on the wiki"),
        (reply(200, {"query": {"pages": [{"title": "Another Page", "revisions": [{"revid": 1, "slots": {"main": {"content": "x"}}}]}]}}), "the answer is about another page"),
        (reply(200, {"query": {"pages": [{"title": "Patch Notes", "revisions": [{"revid": 1, "slots": {"main": {"content": 5}}}]}]}}), "no text in the answer"),
        (reply(200, {"query": {"pages": []}}), "no text in the answer"),
        (reply(200, {"error": {"code": "maxlag", "info": "busy"}}), "the wiki answered with an error"),
        (reply(200, {"query": {}}), "no text in the answer"),
    ],
)
def test_patch_notes_answers_that_are_not_the_page_are_unreachable(tmp_path, answer, reason):
    assert f"- patch notes: unreachable ({reason})" in report(run(tmp_path, net=Net(patch_notes=answer)))


@pytest.mark.parametrize(
    "answer",
    [
        reply(200, {"error": {"code": "maxlag", "info": "waiting for a database server"}}),
        reply(200, {"query": {"recentchanges": "none"}}),
        reply(200, {"query": {"recentchanges": [3]}}),
        reply(200, {"batchcomplete": True}),
    ],
)
def test_changes_answers_that_are_not_a_list_of_changes_are_unreachable(tmp_path, answer):
    text = report(run(tmp_path, net=Net(changes_1=answer)))
    assert "unreachable" in text and "`Zorblax Ring`" not in text


# ---- robots.txt --------------------------------------------------------------------------------------------------------------------------------------


def test_a_wiki_whose_robots_file_forbids_the_api_is_not_asked_and_is_unreachable(tmp_path):
    result = run(tmp_path, net=Net(robots_wiki=reply(200, "User-agent: *\nDisallow: /api.php\n")))
    assert result.transport.paths(WIKI) == ["/robots.txt"]
    text = report(result)
    assert "unreachable (robots.txt of eqlwiki.com does not allow /api.php)" in text
    assert f"- gear: recorded" in text  # (another host is another matter)


def test_a_robots_file_for_this_program_by_name_is_honoured(tmp_path):
    result = run(tmp_path, net=Net(robots_wiki=reply(200, "User-agent: TrioForge-checks\nDisallow: /\n\nUser-agent: *\nAllow: /\n")))
    assert result.transport.paths(WIKI) == ["/robots.txt"]


def test_eqltools_robots_can_forbid_one_file_and_leave_the_other(tmp_path):
    result = run(tmp_path, net=Net(robots_tools=reply(200, "User-agent: *\nDisallow: /gear/\n")))
    assert result.transport.paths(TOOLS) == ["/robots.txt", "/companion/data/quest-items.json"]
    text = report(result)
    assert "- gear: unreachable (robots.txt of eqltools.com does not allow /gear/data/gear-data.json)" in text
    assert "- quests: recorded" in text


def test_a_robots_file_that_cannot_be_read_leaves_its_host_alone(tmp_path):
    result = run(tmp_path, net=Net(robots_tools=reply(503)))
    assert result.transport.paths(TOOLS) == ["/robots.txt"]
    assert "robots.txt of eqltools.com could not be read (HTTP 503)" in report(result)


# ---- the pace, the user agent, the hosts --------------------------------------------------------------------------------------------------------------


def test_a_whole_run_goes_a_request_a_second_in_the_order_wiki_then_tools(tmp_path):
    result = run(tmp_path)
    assert [path.split("?")[0] for path in result.transport.paths()] == [
        "/robots.txt",
        "/api.php",
        "/api.php",
        "/api.php",
        "/robots.txt",
        "/gear/data/gear-data.json",
        "/companion/data/quest-items.json",
    ]
    assert result.transport.starts == [float(n) for n in range(7)]


def test_every_request_has_the_user_agent_that_names_the_project_and_the_about_page_of_the_site(tmp_path):
    result = run(tmp_path)
    assert {call[2]["User-Agent"] for call in result.transport.calls} == {USER_AGENT}
    assert "TrioForge" in USER_AGENT and "(+https://trioforge.pages.dev/about/;" in USER_AGENT and "github" not in USER_AGENT


def test_only_eqlwiki_and_eqltools_are_asked_by_get_and_no_issue_can_be_opened(tmp_path):
    result = run(tmp_path)
    assert {urllib.parse.urlsplit(url).netloc for url in result.transport.urls} == {WIKI, TOOLS}
    assert all(url.startswith("https://") for url in result.transport.urls)
    source = SCRIPT.read_text(encoding="utf-8").lower()
    assert "subprocess" not in source and "api.github.com" not in source and "eqlegendstools" not in source  # (no tool to open an issue with, no other site)


# ---- the stamp -----------------------------------------------------------------------------------------------------------------------------------------


def test_the_stamp_is_written_when_the_run_finishes(tmp_path):
    result = run(tmp_path)
    assert (result.out / "sources-check.last-run").read_text(encoding="utf-8") == "2026-10-18T10:00:03Z\n"


def test_the_stamp_is_written_whatever_the_run_found_even_when_nothing_could_be_read(tmp_path):
    everything_down = {name: OSError("down") for name in ("robots_wiki", "robots_tools")}
    result = run(tmp_path, net=Net(**everything_down))
    assert result.code == 0
    assert (result.out / "sources-check.last-run").read_text(encoding="utf-8") == "2026-10-18T10:00:03Z\n"
    text = report(result)
    assert summary(text) == "wiki changes unreachable; EQL Tools: gear unreachable, quests unreachable; patch notes unreachable; 4 unreachable"
    assert not re.search(r"^- .*: (changed|unchanged|recorded)", text, re.M)  # (no source claims a result)
    assert "`Zorblax Ring`" not in text


def test_the_stamp_takes_the_time_the_run_finishes_not_the_time_it_started(tmp_path):
    times = iter([NOW, NOW + datetime.timedelta(seconds=40)])
    fake_time = FakeTime()
    out = tmp_path / "checks"
    sc.main(
        ["--catalog", str(FIXTURES / "catalog.json"), "--out", str(out)],
        transport=FakeTransport(fake_time, Net()),
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        now=lambda: next(times, NOW + datetime.timedelta(seconds=40)),
    )
    assert (out / "sources-check.last-run").read_text(encoding="utf-8") == "2026-10-18T10:00:43Z\n"
    assert (out / REPORT).exists()  # (the report is named for the time the run began)


def test_the_release_build_reads_the_stamp_the_check_leaves(tmp_path):
    result = run(tmp_path)
    when = NOW + datetime.timedelta(days=3)
    assert release.scheduled_warnings(result.out, when, names=["sources-check"]) == []
    (warning,) = release.scheduled_warnings(result.out, NOW + datetime.timedelta(days=11), names=["sources-check"])
    assert "sources-check" in warning and "11 days" in warning


def test_the_stamp_is_the_name_the_release_build_looks_for():
    assert sc.NAME in release.SCHEDULED_CHECKS


# ---- the files and what is printed ----------------------------------------------------------------------------------------------------------------


def test_the_output_is_the_counts_and_the_place_of_the_report(tmp_path, capsys):
    run(tmp_path)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "sources-check: 4 catalog titles changed; EQL Tools: gear recorded, quests recorded; patch notes recorded; 0 unreachable"
    assert len(lines) == 2 and lines[1].startswith("report: ") and lines[1].endswith(REPORT)
    run(tmp_path)
    assert capsys.readouterr().out.splitlines()[0] == "sources-check: 4 catalog titles changed; EQL Tools: gear unchanged, quests unchanged; patch notes unchanged; 0 unreachable"


def test_the_output_says_what_could_not_be_read(tmp_path, capsys):
    run(tmp_path, net=Net(changes_1=reply(500), gear=reply(500), patch_notes=reply(500)))
    first = capsys.readouterr().out.splitlines()[0]
    assert first == "sources-check: wiki changes unreachable; EQL Tools: gear unreachable, quests recorded; patch notes unreachable; 3 unreachable"


def test_one_change_and_none_are_worded_as_one_and_none(tmp_path, capsys):
    only_one = {"query": {"recentchanges": [{"type": "edit", "ns": 0, "title": "Zorblax Ring", "revid": 139001, "timestamp": "2026-10-12T09:15:00Z"}]}}
    run(tmp_path, net=Net(changes_1=reply(200, only_one)))
    assert "1 catalog title changed;" in capsys.readouterr().out
    assert "1 change in the main namespace; 1 of the changed pages is in the catalog" in report(SimpleNamespace(out=tmp_path / "checks"))
    nothing = {"query": {"recentchanges": []}}
    run(tmp_path / "none", net=Net(changes_1=reply(200, nothing)))
    assert "no catalog title changed;" in capsys.readouterr().out
    assert "0 changes in the main namespace; none of the changed pages is in the catalog." in report(SimpleNamespace(out=tmp_path / "none" / "checks"))


def test_the_report_is_named_for_the_utc_time_the_run_began(tmp_path):
    plus_two = datetime.timezone(datetime.timedelta(hours=2))
    result = run(tmp_path, now=datetime.datetime(2026, 10, 18, 12, 0, 3, tzinfo=plus_two))
    assert result.report_name == REPORT == "sources-check-2026-10-18T100003Z.md"
    assert [path.name for path in result.out.glob("*.md")] == [REPORT]


def test_a_second_run_of_the_day_leaves_the_first_report_as_it_was(tmp_path):
    first = run(tmp_path)
    before = report(first)
    assert "recorded" in before
    second = run(tmp_path, now=NOW + datetime.timedelta(hours=3))
    assert sorted(path.name for path in second.out.glob("*.md")) == [REPORT, "sources-check-2026-10-18T130003Z.md"]
    assert report(first) == before and "unchanged" in report(second)


def test_a_report_is_never_overwritten_not_even_by_a_run_in_the_same_second(tmp_path):
    first = run(tmp_path)
    before = report(first)
    second = run(tmp_path)
    third = run(tmp_path)
    stem = REPORT.removesuffix(".md")
    assert sorted(path.name for path in first.out.glob("*.md")) == sorted([REPORT, f"{stem}-2.md", f"{stem}-3.md"])
    assert (second.report_name, third.report_name) == (f"{stem}-2.md", f"{stem}-3.md")
    assert report(first) == before and "unchanged" in report(second) and "unchanged" in report(third)


def test_a_report_of_that_name_that_someone_made_is_not_replaced_whatever_it_holds(tmp_path):
    out = tmp_path / "checks"
    out.mkdir()
    (out / REPORT).write_text("kept\n", encoding="utf-8")
    result = run(tmp_path)
    assert (out / REPORT).read_text(encoding="utf-8") == "kept\n" and result.report_name == REPORT.removesuffix(".md") + "-2.md"
    assert "recorded" in report(result)


def test_the_line_that_says_where_the_report_is_names_the_report_that_was_written(tmp_path, capsys):
    run(tmp_path)
    capsys.readouterr()
    run(tmp_path)
    assert capsys.readouterr().out.splitlines()[1].endswith(REPORT.removesuffix(".md") + "-2.md")


def test_the_report_goes_where_it_is_told_and_that_folder_is_made(tmp_path):
    result = run(tmp_path / "deep" / "er")
    assert (result.out / REPORT).is_file() and (result.out / "sources-check.state.json").is_file() and (result.out / "sources-check.last-run").is_file()


def test_the_report_is_text_with_unix_line_ends_and_says_the_maintainer_opens_any_issue(tmp_path):
    raw = (run(tmp_path).out / REPORT).read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    assert "open an issue by hand" in raw.decode("utf-8")


# ---- the catalog and the arguments ---------------------------------------------------------------------------------------------------------------


def test_an_item_without_a_wiki_page_is_not_a_title_to_watch(tmp_path):
    assert "Brambletop Charm" not in report(run(tmp_path))
    titles = sc.read_catalog(FIXTURES / "catalog.json")
    assert sorted(titles) == ["Draxil's Belt", "Mirrowen Cloak", "Quenfel`s Cap", "Rune: Sorvath", "Zorblax Ring"]
    assert titles["Zorblax Ring"].key == "w101" and titles["Zorblax Ring"].revid == 138180


@pytest.mark.parametrize("content", ["", "{not json", "[]", '{"items": 5}', '{"items": [3]}', '{"version": 1}'])
def test_a_catalog_that_is_missing_or_not_a_catalog_refuses_the_run_in_one_line(tmp_path, capsys, content):
    bad = tmp_path / "catalog.json"
    bad.write_text(content, encoding="utf-8")
    result = run(tmp_path / "run", catalog=bad)
    err = capsys.readouterr().err
    assert result.code == 2 and err.startswith("sources-check: ") and "catalog" in err and len(err.splitlines()) == 1
    assert result.transport.calls == [] and only_the_log(tmp_path / "run" / "checks")  # no request, no report, no record, no stamp: only the line of the log


def test_a_catalog_that_is_not_there_refuses_the_run(tmp_path, capsys):
    result = run(tmp_path, catalog=tmp_path / "no-such-catalog.json")
    assert result.code == 2 and "catalog" in capsys.readouterr().err and not (result.out / "sources-check.last-run").exists()


def test_the_run_needs_no_account_and_says_who_runs_it_by_the_about_page_of_the_site(tmp_path):
    result = run(tmp_path)
    assert result.code == 0 and result.transport.calls
    assert {call[2]["User-Agent"] for call in result.transport.calls} == {USER_AGENT}


def test_another_contact_page_can_be_given_and_it_is_the_one_the_user_agent_carries(tmp_path):
    result = run(tmp_path, "--contact", "https://example.invalid/hello/")
    (agent,) = {call[2]["User-Agent"] for call in result.transport.calls}
    assert agent != USER_AGENT and "(+https://example.invalid/hello/;" in agent


@pytest.mark.parametrize("contact", ["", "no-address", "ftp://example.invalid/", "https://user:secret@example.invalid/", "https://example.invalid/a b", "https://example.invalid/;x"])
def test_a_contact_that_is_not_an_address_refuses_the_run(tmp_path, capsys, contact):
    fake_time = FakeTime()
    transport = FakeTransport(fake_time, Net())
    argv = [f"--contact={contact}", "--catalog", str(FIXTURES / "catalog.json"), "--out", str(tmp_path / "checks")]
    assert sc.main(argv, transport=transport, clock=fake_time.clock, sleep=fake_time.sleep, now=lambda: NOW) == 2
    err = capsys.readouterr().err
    assert "contact" in err.lower() and len(err.splitlines()) == 1 and transport.calls == [] and only_the_log(tmp_path / "checks")


def test_the_option_that_named_the_account_is_gone():
    with pytest.raises(SystemExit) as stop:
        sc.main(["--owner", "someone"])
    assert stop.value.code == 2


def test_an_unknown_option_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as stop:
        sc.main(["--no-such-option"])
    assert stop.value.code == 2


@pytest.mark.parametrize("days", ["0", "-3", "x", "400"])
def test_a_number_of_days_that_makes_no_sense_is_a_usage_error(tmp_path, days):
    with pytest.raises(SystemExit) as stop:
        sc.main(["--days", days, "--out", str(tmp_path)])
    assert stop.value.code == 2


# ---- how the run ends --------------------------------------------------------------------------------------------------------------------------------


def test_a_write_that_fails_ends_the_run_in_one_line_and_leaves_no_stamp(tmp_path, capsys, monkeypatch):
    real = common.write_text_atomic

    def fail_on_report(path, text):
        if str(path).endswith(".md"):
            raise OSError("the disk is full")
        return real(path, text)

    monkeypatch.setattr(common, "write_text_atomic", fail_on_report)
    result = run(tmp_path)
    err = capsys.readouterr().err
    assert result.code == 2 and err.startswith("sources-check: ") and len(err.splitlines()) == 1
    assert not (result.out / "sources-check.last-run").exists() and not (result.out / "sources-check.state.json").exists()


def test_an_interrupted_run_ends_with_130_and_leaves_no_stamp(tmp_path):
    result = run(tmp_path, net=Net(gear=KeyboardInterrupt()))
    assert result.code == 130 and not (result.out / "sources-check.last-run").exists()


# ---- the dry run: recorded answers, no network ---------------------------------------------------------------------------------------------------------


def test_a_dry_run_replays_the_recorded_answers_and_never_makes_a_network_request(tmp_path, monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError("a dry run asked for the real transport")

    monkeypatch.setattr(common, "real_transport", no_network)
    out = tmp_path / "scratch"
    code = sc.main(["--dry-run", str(FIXTURES), "--catalog", str(FIXTURES / "catalog.json"), "--out", str(out)], now=lambda: NOW)
    assert code == 0
    assert "`Zorblax Ring`" in (out / REPORT).read_text(encoding="utf-8")
    assert capsys.readouterr().out.splitlines()[0].startswith("sources-check: 4 catalog titles changed")


def real_folder_spellings(folder: Path) -> list[Path]:
    """The folder of the real checks as it can be written: as it is, with a dot, with a trailing separator, round a sub-folder, and (on Windows) in another case."""
    spellings = [folder, folder / ".", Path(str(folder) + os.sep), folder / "sub" / ".."]
    if sys.platform == "win32":
        spellings.append(Path(str(folder).swapcase()))
    return spellings


def test_a_dry_run_cannot_write_into_the_folder_of_the_real_checks_however_it_is_spelled(tmp_path, capsys):
    folder = Path(os.environ["TRIOFORGE_CHECKS_DIR"])
    for spelling in real_folder_spellings(folder):
        argv = ["--dry-run", str(FIXTURES), "--catalog", str(FIXTURES / "catalog.json"), "--out", str(spelling)]
        assert sc.main(argv, now=lambda: NOW) == 2, spelling
        err = capsys.readouterr().err
        assert err.startswith("sources-check: a dry run cannot write into the folder of the real checks") and len(err.splitlines()) == 1, spelling
    assert not folder.exists() or list(folder.iterdir()) == []  # (no report, no record, no stamp, and not even a line of the log)
    other = tmp_path / "scratch"
    assert sc.main(["--dry-run", str(FIXTURES), "--catalog", str(FIXTURES / "catalog.json"), "--out", str(other)], now=lambda: NOW) == 0  # (any other folder is fine)


def test_a_dry_run_in_a_scratch_folder_logs_there_like_any_run(tmp_path):
    out = tmp_path / "scratch"
    assert sc.main(["--dry-run", str(FIXTURES), "--catalog", str(FIXTURES / "catalog.json"), "--out", str(out)], now=lambda: NOW) == 0
    (line,) = log_lines(out)
    assert line.startswith("2026-10-18T10:00:03Z ok ")


def test_a_real_run_may_write_into_the_folder_of_the_real_checks_named_with_out(tmp_path):
    folder = Path(os.environ["TRIOFORGE_CHECKS_DIR"])
    fake_time = FakeTime()
    argv = ["--catalog", str(FIXTURES / "catalog.json"), "--out", str(folder)]
    assert sc.main(argv, transport=FakeTransport(fake_time, Net()), clock=fake_time.clock, sleep=fake_time.sleep, now=lambda: NOW) == 0
    assert (folder / "sources-check.last-run").is_file()


@pytest.mark.parametrize("option", ["--out", "--dry-run", "--catalog"])
@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_path_is_refused_and_is_not_the_working_folder(tmp_path, monkeypatch, option, empty):
    monkeypatch.chdir(tmp_path)
    fake_time = FakeTime()
    argv = ["--catalog", str(FIXTURES / "catalog.json"), "--out", str(tmp_path / "scratch")]
    if option == "--catalog":
        argv = argv[2:] + ["--catalog", empty]
    elif option == "--out":
        argv = argv[:2] + ["--out", empty]
    else:
        argv += ["--dry-run", empty]
    with pytest.raises(SystemExit) as stopped:
        sc.main(argv, transport=FakeTransport(fake_time, Net()), clock=fake_time.clock, sleep=fake_time.sleep, now=lambda: NOW)
    assert stopped.value.code == 2
    assert sorted(path.name for path in tmp_path.iterdir()) == []  # (nothing was written in the working folder, and nothing else made there)


def test_a_dry_run_must_say_where_to_write_so_that_it_cannot_replace_a_real_report(tmp_path, capsys):
    assert sc.main(["--dry-run", str(FIXTURES), "--catalog", str(FIXTURES / "catalog.json")], now=lambda: NOW) == 2
    assert "--out" in capsys.readouterr().err


def test_a_dry_run_with_recorded_answers_that_cannot_be_read_is_refused_in_one_line(tmp_path, capsys):
    assert sc.main(["--dry-run", str(tmp_path / "nothing-here"), "--catalog", str(FIXTURES / "catalog.json"), "--out", str(tmp_path / "o")], now=lambda: NOW) == 2
    err = capsys.readouterr().err
    assert err.startswith("sources-check: ") and len(err.splitlines()) == 1


def test_the_command_runs_on_recorded_answers_and_leaves_what_the_release_build_reads(tmp_path):
    out = tmp_path / "scratch"
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", str(FIXTURES), "--catalog", str(FIXTURES / "catalog.json"), "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) == 2 and lines[0].startswith("sources-check: 4 catalog titles changed") and lines[1].startswith("report: ")
    assert done.stderr == ""
    stamp = (out / "sources-check.last-run").read_text(encoding="utf-8")
    assert re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z\n", stamp)
    assert release.scheduled_warnings(out, common.parse_utc(stamp) + datetime.timedelta(days=2), names=["sources-check"]) == []


def test_the_command_reports_a_usage_error_with_status_2(tmp_path):
    done = subprocess.run([sys.executable, str(SCRIPT), "--no-such-option"], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert done.returncode == 2 and done.stdout == ""
