"""Tests for the files that put the scheduled checks on the maintainer's computer: the Windows Task Scheduler templates in ``scripts/scheduler/`` and the runbook
``docs/runbook-weekly.md``, and for the stamps of the three checks as the release build reads them.

The templates are held to the settings the checks need (a missed run is made up, the checks run on battery and wake the computer, with the user's own account and no
stored password, so only while the user is logged on), to the schedule of each (weekly or monthly), and to what they run. They hold placeholders instead of the places
of any computer. Where the machine is Windows, Task Scheduler's own parser validates each template without registering anything.
"""

from __future__ import annotations

import calendar
import datetime
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from checks_helpers import REPO
from test_repo_files import PRIVATE_DOCUMENT_REFERENCE, PRIVATE_LOCATION
from test_site_build import need_node

import checks_common as common
from trioforge.precompute import release

SCHEDULER = REPO / "scripts" / "scheduler"
RUNBOOK = REPO / "docs" / "runbook-weekly.md"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
NAMES = ("sources-check", "smoke-live", "pins-check")
WEEKLY = ("sources-check", "smoke-live")
PLACEHOLDERS = {
    "sources-check": {"@REPO@", "@SOURCES_OPTIONS@"},
    "pins-check": {"@REPO@"},
    "smoke-live": {"@REPO@", "@NODE@", "@SMOKE_OPTIONS@"},
}
SCRIPT_OF = {"sources-check": "scripts\\sources_check.py", "pins-check": "scripts\\pins_check.py", "smoke-live": "scripts\\smoke_live.mjs"}
MONTHS = list(calendar.month_name)[1:]
WEEKDAYS = set(calendar.day_name)
NOW = datetime.datetime(2026, 10, 18, 12, 0, 0, tzinfo=datetime.timezone.utc)


def template(name: str) -> ET.Element:
    return ET.parse(SCHEDULER / f"{name}.xml").getroot()


def text_of(root: ET.Element, path: str) -> str | None:
    found = root.find(path, NS)
    return None if found is None else (found.text or "").strip()


# ---- the templates: the settings every one of them has ---------------------------------------------------------------------------------------------------


def test_there_is_a_template_for_each_check_and_for_no_other():
    assert sorted(path.name for path in SCHEDULER.glob("*")) == sorted(f"{name}.xml" for name in NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_a_template_is_a_task_of_task_scheduler(name):
    root = template(name)
    assert root.tag == f"{{{NS['t']}}}Task" and root.get("version") in ("1.2", "1.3", "1.4")
    raw = (SCHEDULER / f"{name}.xml").read_bytes()
    assert raw.startswith(b"<?xml") and b'encoding="UTF-8"' in raw[:80]  # (the install turns it into UTF-16, which is what Task Scheduler writes and reads)
    assert b"\r" not in raw and raw.endswith(b"\n")
    assert text_of(root, "t:RegistrationInfo/t:URI") == f"\\TrioForge\\{name}"
    assert text_of(root, "t:RegistrationInfo/t:Description")


@pytest.mark.parametrize("name", NAMES)
def test_a_missed_run_is_made_up_and_the_check_runs_on_battery_and_wakes_the_computer(name):
    settings = lambda tag: text_of(template(name), f"t:Settings/t:{tag}")  # noqa: E731
    assert settings("StartWhenAvailable") == "true"
    assert settings("DisallowStartIfOnBatteries") == "false"
    assert settings("StopIfGoingOnBatteries") == "false"
    assert settings("WakeToRun") == "true"
    assert settings("RunOnlyIfNetworkAvailable") == "true"
    assert settings("RunOnlyIfIdle") == "false"
    assert settings("Enabled") == "true"
    assert settings("MultipleInstancesPolicy") == "IgnoreNew"


@pytest.mark.parametrize("name", NAMES)
def test_a_check_that_hangs_is_ended(name):
    limit = text_of(template(name), "t:Settings/t:ExecutionTimeLimit")
    found = re.fullmatch(r"PT([0-9]+)H", limit or "")
    assert found and 1 <= int(found.group(1)) <= 2


@pytest.mark.parametrize("name", NAMES)
def test_a_check_runs_with_the_users_own_account_only_while_they_are_logged_on_and_with_no_stored_password(name):
    root = template(name)
    (principal,) = root.findall("t:Principals/t:Principal", NS)
    assert text_of(principal, "t:LogonType") == "InteractiveToken"  # (run only when the user is logged on: no password is stored)
    assert text_of(principal, "t:RunLevel") == "LeastPrivilege"
    assert principal.find("t:UserId", NS) is None  # (the task is made for whoever installs it)
    assert principal.find("t:GroupId", NS) is None
    assert root.find(".//t:Password", NS) is None
    raw = (SCHEDULER / f"{name}.xml").read_text(encoding="utf-8").lower()
    assert "password" not in raw and "s4u" not in raw and "highest" not in raw


@pytest.mark.parametrize("name", NAMES)
def test_a_check_has_one_schedule_and_it_is_a_calendar(name):
    root = template(name)
    (trigger,) = root.findall("t:Triggers/*", NS)
    assert trigger.tag == f"{{{NS['t']}}}CalendarTrigger"
    assert text_of(trigger, "t:Enabled") == "true"
    assert re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-2][0-9]:[0-5][0-9]:00", text_of(trigger, "t:StartBoundary") or "")


@pytest.mark.parametrize("name", WEEKLY)
def test_the_sources_check_and_the_smoke_check_run_every_week(name):
    (trigger,) = template(name).findall("t:Triggers/*", NS)
    weekly = trigger.find("t:ScheduleByWeek", NS)
    assert weekly is not None and text_of(weekly, "t:WeeksInterval") == "1"
    days = [child.tag.split("}")[1] for child in weekly.find("t:DaysOfWeek", NS)]
    assert len(days) == 1 and days[0] in WEEKDAYS
    assert trigger.find("t:ScheduleByMonth", NS) is None and trigger.find("t:ScheduleByDay", NS) is None


def test_the_pins_check_runs_every_month():
    (trigger,) = template("pins-check").findall("t:Triggers/*", NS)
    monthly = trigger.find("t:ScheduleByMonth", NS)
    assert monthly is not None
    assert [child.text for child in monthly.find("t:DaysOfMonth", NS)] == ["1"]
    assert [child.tag.split("}")[1] for child in monthly.find("t:Months", NS)] == MONTHS
    assert trigger.find("t:ScheduleByWeek", NS) is None and trigger.find("t:ScheduleByDay", NS) is None


def test_the_two_weekly_checks_do_not_start_at_the_same_time():
    starts = [text_of(template(name).find("t:Triggers/t:CalendarTrigger", NS), "t:StartBoundary") for name in WEEKLY]
    assert len(set(starts)) == 2


# ---- what they run ----------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_a_check_runs_one_program_in_the_repository(name):
    (action,) = template(name).findall("t:Actions/*", NS)
    assert action.tag == f"{{{NS['t']}}}Exec"
    assert text_of(action, "t:WorkingDirectory") == "@REPO@"
    assert SCRIPT_OF[name] in (text_of(action, "t:Arguments") or "")


@pytest.mark.parametrize("name", ["sources-check", "pins-check"])
def test_the_python_checks_run_with_the_python_of_the_virtual_environment_without_a_console_window(name):
    (action,) = template(name).findall("t:Actions/t:Exec", NS)
    assert text_of(action, "t:Command") == "@REPO@\\.venv\\Scripts\\pythonw.exe"
    assert text_of(action, "t:Arguments") == SCRIPT_OF[name] + (" @SOURCES_OPTIONS@" if name == "sources-check" else "")  # (the sources can be left out, one by one: --skip)


def test_the_smoke_check_runs_with_node():
    (action,) = template("smoke-live").findall("t:Actions/t:Exec", NS)
    assert text_of(action, "t:Command") == "@NODE@"
    assert text_of(action, "t:Arguments") == "scripts\\smoke_live.mjs @SMOKE_OPTIONS@"


@pytest.mark.parametrize("name", NAMES)
def test_a_template_holds_placeholders_and_the_place_of_no_computer(name):
    raw = (SCHEDULER / f"{name}.xml").read_text(encoding="utf-8")
    assert set(re.findall(r"@[A-Z_]+@", raw)) == PLACEHOLDERS[name]
    assert not PRIVATE_LOCATION.search(raw.replace("@REPO@\\", "REPO/"))
    assert "@" not in re.sub(r"@[A-Z_]+@", "", raw)  # (no address of a person, no other use of the sign)


@pytest.mark.parametrize("name", NAMES)
def test_the_description_of_a_template_does_not_send_the_reader_to_a_build_folder_of_a_checkout(name):
    description = text_of(template(name), "t:RegistrationInfo/t:Description") or ""
    assert "build\\checks" not in description and "build/checks" not in description
    assert "folder of the checks" in description  # (where the files are: outside every worktree)


@pytest.mark.parametrize("name", NAMES)
def test_the_text_of_a_template_cites_nothing_private(name):
    raw = (SCHEDULER / f"{name}.xml").read_text(encoding="utf-8")
    assert not [line for line in raw.splitlines() if PRIVATE_DOCUMENT_REFERENCE.search(line)]


def fill(name: str) -> str:
    """The template as the install step of the runbook fills it, with invented values."""
    text = (SCHEDULER / f"{name}.xml").read_text(encoding="utf-8")
    values = {"@REPO@": "C:\\work\\trioforge", "@NODE@": "C:\\tools\\node.exe", "@SMOKE_OPTIONS@": "", "@SOURCES_OPTIONS@": "--skip eqltools"}
    for key, value in values.items():
        text = text.replace(key, value)
    return text


@pytest.mark.parametrize("name", NAMES)
def test_a_filled_template_is_xml_with_no_placeholder_left(name):
    text = fill(name)
    assert "@" not in text
    ET.fromstring(text.replace('encoding="UTF-8"', "", 1))  # (parses)


@pytest.mark.skipif(sys.platform != "win32" or shutil.which("powershell") is None, reason="Task Scheduler's own parser is on Windows")
@pytest.mark.parametrize("name", NAMES)
def test_task_scheduler_accepts_a_filled_template_without_registering_it(name, tmp_path):
    xml = tmp_path / f"{name}.xml"
    xml.write_bytes(b"\xff\xfe" + fill(name).replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16-le"))
    script = tmp_path / "validate.ps1"
    script.write_text(
        "param($file)\n"
        "$service = New-Object -ComObject Schedule.Service\n"
        "$service.Connect()\n"
        "$definition = $service.NewTask(0)\n"
        "$definition.XmlText = [IO.File]::ReadAllText($file)\n"
        "$folder = $service.GetFolder('\\')\n"
        "# TASK_VALIDATE_ONLY (1): the definition is checked and nothing is registered; TASK_LOGON_INTERACTIVE_TOKEN (3)\n"
        "$null = $folder.RegisterTaskDefinition('TrioForge\\validate-only', $definition, 1, $null, $null, 3)\n"
        "'valid'\n",
        encoding="utf-8",
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), str(xml)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0 and done.stdout.strip() == "valid", done.stderr[-600:]


# ---- the runbook -------------------------------------------------------------------------------------------------------------------------------------


def runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def sections(text: str) -> dict[str, str]:
    """The text under each heading of the runbook, by the lower-case words of the heading."""
    found: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^#{1,4} (.+)$", line)
        if heading:
            current = heading.group(1).strip().lower()
            found[current] = ""
        elif current is not None:
            found[current] += line + "\n"
    return found


def test_the_runbook_is_a_document_of_the_repository_with_the_four_things_it_is_for():
    text = runbook()
    assert text.startswith("# ") and text.endswith("\n") and "\r" not in text
    headings = " | ".join(sections(text))
    for wanted in ("install", "report", "issue", "stamp"):
        assert wanted in headings, wanted


def test_the_runbook_says_how_to_install_the_templates_with_schtasks():
    text = runbook()
    assert "schtasks /create" in text and "/xml" in text and "scripts/scheduler" in text.replace("\\", "/")
    for placeholder in ("@REPO@", "@NODE@", "@SMOKE_OPTIONS@", "@SOURCES_OPTIONS@"):
        assert placeholder in text, placeholder
    assert "--skip eqltools" in text and "HTTP 403" in text  # (a source that refuses the check can be left out of every run)
    assert "/tn" in text and "TrioForge\\" in text  # (the tasks are made in a folder of their own, TrioForge)
    assert "Get-Location" not in text and "main checkout" in text.lower()  # (the tasks are made from the main checkout, with its own path: a worktree that is removed takes them with it)
    for setting in ("StartWhenAvailable", "battery", "wake"):
        assert setting.lower() in text.lower(), setting
    assert "logged on" in text and "password" in text.lower()


def test_the_runbook_names_each_check_its_schedule_its_report_and_its_stamp():
    text = runbook()
    for name in NAMES:
        assert name in text
        assert f"{name}.last-run" in text
    for script in ("scripts/sources_check.py", "scripts/pins_check.py", "scripts/smoke_live.mjs"):
        assert script in text
    assert "TRIOFORGE_CHECKS_DIR" in text and ".local/state/trioforge/checks" in text  # (the one folder outside every worktree, the same one on Windows)
    assert "%LOCALAPPDATA%\\TrioForge" not in text and "private copy" in text  # (the old default is gone; the app data is named only to say why it is not used)
    assert "sources-check-" in text and "pins-check-" in text
    assert "weekly" in text.lower() and "monthly" in text.lower()


def test_the_runbook_says_what_each_report_means():
    parts = sections(runbook())
    where = " | ".join(parts)
    for kind in ("sources-check", "pins-check", "smoke-live"):
        assert kind in where, kind
    body = runbook().lower()
    for word in ("unreachable", "changed", "recorded", "unchanged", "too young", "moved", "14 days", "not checked", "newer"):
        assert word in body, word
    for failure in ("answered", "content-security-policy", "x-robots-tag", "console error", "theme button", "data release", "404 page"):
        assert failure in body, failure
    assert "403" in body and "refusing" in body, "a site that answers 403 is refusing the check, and the runbook says not to get round it"


def test_the_runbook_says_when_to_open_an_issue_and_that_the_checks_open_none():
    text = runbook()
    lowered = text.lower()
    assert "open an issue by hand" in lowered
    assert re.search(r"\b(never|none of them|no check)\b[^.]{0,30}\bopens? an issue", lowered), "the runbook says that the checks open no issue"
    assert "when to open an issue" in lowered


def test_the_runbook_says_how_to_read_the_stamps_and_what_the_release_build_does_with_them():
    text = runbook().lower()
    for word in (".last-run", "utc", "10 days", "release build", "warn", "never ran", "finished"):
        assert word in text, word
    assert "smoke-live" in text and "only" in text  # (it is written only when the check passes)


def test_the_runbook_says_how_to_run_a_check_by_hand_and_after_a_deploy():
    text = runbook()
    for word in ("--expect-data", "--indexable", "--dry-run", "--base", "--pace", "--contact"):
        assert word in text, word
    assert "after a deploy" in text.lower() and "one request a second" in text.lower()


def test_the_runbook_names_no_person_and_no_computer_and_cites_nothing_private():
    text = runbook()
    assert not [line for line in text.splitlines() if PRIVATE_LOCATION.search(line)], "a place on a computer"
    assert not [line for line in text.splitlines() if PRIVATE_DOCUMENT_REFERENCE.search(line)], "a private document"
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text), "an e-mail address"
    assert all(account == "<owner>" for account in re.findall(r"github\.com/([^/\s)]+)", text)), "an account name that is not the placeholder"


def test_the_runbook_is_the_one_the_contributor_guide_points_to():
    guide = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "docs/runbook-weekly.md" in guide


# ---- the stamps, as the release build reads them ----------------------------------------------------------------------------------------------------------


def test_the_names_the_release_build_looks_for_are_the_weekly_checks_and_the_monthly_one_is_not_among_them():
    assert set(release.SCHEDULED_CHECKS) == set(WEEKLY)
    assert "pins-check" not in release.SCHEDULED_CHECKS


def test_the_stamp_the_smoke_check_writes_is_read_by_the_release_build(tmp_path):
    need_node()
    done = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", "import('./scripts/smoke_live.mjs').then((m) => process.stdout.write(m.stampText(new Date('2026-10-18T09:00:03.456Z'))))"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == "2026-10-18T09:00:03Z\n"
    (tmp_path / "smoke-live.last-run").write_text(done.stdout, encoding="utf-8")
    assert release.scheduled_warnings(tmp_path, NOW, names=["smoke-live"]) == []
    assert len(release.scheduled_warnings(tmp_path, NOW + datetime.timedelta(days=12), names=["smoke-live"])) == 1


def test_the_stamp_of_the_smoke_check_is_the_stamp_of_the_other_two_in_form(tmp_path):
    need_node()
    done = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", "import('./scripts/smoke_live.mjs').then((m) => process.stdout.write(m.stampText(new Date('2026-10-18T10:00:03Z'))))"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )
    assert done.stdout == common.stamp_text(datetime.datetime(2026, 10, 18, 10, 0, 3, tzinfo=datetime.timezone.utc))


@pytest.mark.parametrize("outcome", ["ok", "failed", "refused", "error", "interrupted"])
def test_the_log_line_of_the_smoke_check_is_the_log_line_of_the_other_two_in_form(outcome):
    need_node()
    text = "first\r\nsecond\tthird fourth  " + "x" * 600
    snippet = "import('./scripts/smoke_live.mjs').then((m) => process.stdout.write(m.logLine(new Date('2026-10-18T10:00:03.456Z'), process.argv[1], process.argv[2])))"
    done = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", snippet, outcome, text],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == common.log_line(datetime.datetime(2026, 10, 18, 10, 0, 3, 456000, tzinfo=datetime.timezone.utc), outcome, text)


def test_the_python_checks_write_by_default_into_the_checks_folder_which_the_release_build_reads_and_nothing_into_the_repository(tmp_path, monkeypatch, capsys):
    import pins_check
    import sources_check

    sources = REPO / "fixtures" / "checks" / "sources"
    pins = REPO / "fixtures" / "checks" / "pins"
    folder = tmp_path / "the-checks-folder"
    monkeypatch.setenv("TRIOFORGE_CHECKS_DIR", str(folder))
    repository = tmp_path / "repository"
    repository.mkdir()
    for module in (sources_check, pins_check):
        monkeypatch.setattr(module, "ROOT", repository)
    virtual = common.VirtualTime()
    common_args = dict(clock=virtual.clock, sleep=virtual.sleep, now=lambda: NOW)
    assert sources_check.main(["--catalog", str(sources / "catalog.json")], transport=common.ReplayTransport.from_directory(sources), **common_args) == 0
    assert (
        pins_check.main(["--root", str(pins / "repo")], transport=common.ReplayTransport.from_directory(pins), local_versions={"python": "3.12.7", "node": "24.14.0"}, **common_args)
        == 0
    )
    names = sorted(path.name for path in folder.iterdir())
    for wanted in ("sources-check.last-run", "pins-check.last-run", "sources-check.state.json"):
        assert wanted in names, names
    assert any(name.startswith("sources-check-") and name.endswith(".md") for name in names) and any(name.startswith("pins-check-") and name.endswith(".md") for name in names)
    assert list(repository.iterdir()) == []  # (not a file in the repository: it may be one of many worktrees)
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("report: ")]
    assert len(printed) == 2 and all(line.startswith(f"report: {folder}") for line in printed)
    assert release.scheduled_warnings(None, NOW, names=["sources-check"]) == []  # (the release build, which is given no folder, looks where the checks wrote)


def test_the_runbook_says_what_the_logs_are_and_that_a_report_is_never_replaced():
    text = runbook()
    lowered = text.lower()
    for word in (".log", "200 lines", "pythonw", "refused", "interrupted", "failed", "error"):
        assert word in lowered, word
    assert "never replaced" in lowered and "utc time" in lowered and "a second run on the same day leaves the first report" in lowered


def test_the_runbook_says_that_the_folder_is_the_same_on_windows_and_what_the_variable_may_be():
    text = runbook()
    lowered = text.lower()
    assert "~/.local/state/trioforge/checks" in text and "windows too" in lowered
    assert "counts as unset" in lowered  # (an empty or blank TRIOFORGE_CHECKS_DIR)
    assert "git work tree" in lowered and "absolute" in lowered and "refused" in lowered
    assert "release build" in lowered and "refuse" in lowered


def test_the_runbook_says_that_a_dry_run_cannot_write_into_the_folder_of_the_checks():
    text = runbook()
    assert "never into the folder of the checks unless you name it" not in text  # (it is refused there, however it is named)
    assert "cannot be the folder of the checks" in text


def test_the_runbook_says_that_the_smoke_check_expects_the_release_of_the_newest_pointer():
    text = runbook()
    assert "newest pointer" in text and "releases/" in text and "--expect-data none" in text and "--releases-dir" in text and "--settle" in text


def test_the_install_leaves_eql_tools_out_of_the_weekly_run_until_it_allows_the_check_and_says_when_to_take_that_out():
    text = runbook()
    assert re.search(r"^\$sourcesOptions = '--skip eqltools'", text, re.MULTILINE), "the install defaults to leaving EQL Tools out: it answered the check with HTTP 403, and asking again every week is not polite"
    lowered = text.lower()
    assert "remove `--skip eqltools`" in lowered and "allows the check" in lowered  # (and the line says when)
