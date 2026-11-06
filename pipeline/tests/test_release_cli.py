"""Tests for ``scripts/release-build.py``, the command the maintainer runs on the PC: its arguments, its exit status and what it prints.

The build itself is tested in ``test_release_build.py``; here it is replaced by a recorder, so that the command line is held to what it hands over and to
the way it ends: 0 when a release is built, 2 when one is refused or cannot be built (one line on standard error, no traceback unless TRIOFORGE_DEBUG is
set), 130 when it is interrupted.
"""

from __future__ import annotations

import importlib.util
import io
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from trioforge.precompute import release
from trioforge.precompute.assemble import ReleaseRefused

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "release-build.py"
ARGS = ["--tag", "data-2026-10-17", "--privacy-key", "privacy.key"]


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("release_build_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result(**over):
    values = dict(
        tag="data-2026-10-17", asset=Path("build/release/data-2026-10-17.tar.gz"), asset_sha256="ab" * 32, pointer=Path("releases/data-2026-10-17.json"),
        reports=(Path("reports/a.md"), Path("reports/a.json")), trios=560, files=9000, site_files=9500, changes=12, solver_diffs=0, previous=None, warnings=[], trial=False, outcomes=[],
    )
    values.update(over)
    return SimpleNamespace(**values)


@pytest.fixture
def recorded(monkeypatch):
    calls: list[dict] = []

    def fake(**kwargs):
        calls.append(kwargs)
        kwargs["say"]("a line of counts")
        return result()

    monkeypatch.setattr(release, "build_release", fake)
    return calls


def test_the_arguments_the_build_is_given(script, recorded, capsys):
    assert script.main([*ARGS, "--processes", "7"]) == 0
    (call,) = recorded
    assert call["tag"] == "data-2026-10-17" and call["processes"] == 7 and call["trios"] is None and call["previous"] == "auto"
    assert Path(call["privacy_key"]) == Path("privacy.key").resolve()
    assert not {"seen", "wiki", "client"} & set(call)  # (a release is built from the public catalog alone: wiki is its one evidence level)
    assert Path(call["root"]) == REPO and call["parity_stride"] is None  # (none: the largest stride that is allowed)
    assert "a line of counts" in capsys.readouterr().out


def test_the_default_number_of_processes_leaves_some_cores_free(script, recorded):
    script.main(ARGS)
    assert recorded[0]["processes"] == max(1, (os.cpu_count() or 2) - 4)


def test_the_default_number_of_parity_processes_is_half_the_cores_up_to_twelve(script, recorded):
    script.main(ARGS)
    assert recorded[0]["parity_processes"] == max(1, min(12, (os.cpu_count() or 2) // 2))


def test_the_number_of_parity_processes_is_an_option_of_at_least_one(script, recorded, capsys):
    assert script.main([*ARGS, "--parity-processes", "5"]) == 0
    assert recorded[0]["parity_processes"] == 5
    for bad in ("0", "-3", "many", "2.5"):
        assert script.main([*ARGS, "--parity-processes", bad]) == 2
        assert "parity-processes" in capsys.readouterr().err
    assert len(recorded) == 1


def test_some_trios_make_a_trial_build(script, recorded):
    assert script.main([*ARGS, "--trios", "pal-mnk-ber, war-clr-pal"]) == 0
    assert recorded[0]["trios"] == ("pal-mnk-ber", "war-clr-pal") and recorded[0]["trial"] is True
    script.main(ARGS)
    assert recorded[1]["trial"] is False and recorded[1]["trios"] is None


def test_the_other_options_are_passed_on(script, recorded, tmp_path):
    script.main([
        *ARGS, "--catalog", str(tmp_path / "catalog.json"), "--previous", "none", "--parity-stride", "50", "--build-dir", str(tmp_path / "build"),
    ])  # fmt: skip
    call = recorded[0]
    assert Path(call["catalog"]) == tmp_path / "catalog.json"
    assert call["previous"] == "none" and call["parity_stride"] == 50 and Path(call["build_dir"]) == tmp_path / "build"


@pytest.mark.parametrize(
    "bad",
    [
        ["--tag", "data-2026-10-1", "--privacy-key", "k"],
        ["--tag", "data-2026-10-17"],
        ["--privacy-key", "k"],
        [*ARGS, "--seen", "seen-flags.json"],  # (gone: the release builds from the public catalog, and wiki is the one evidence level)
        [*ARGS, "--wiki", "sources/eqlwiki/2026-10-14"],  # (gone with the catalog that was built from it)
        [*ARGS, "--client", "derived/client"],
        [*ARGS, "--processes", "0"],
        [*ARGS, "--processes", "many"],
        [*ARGS, "--trios", "pal-mnk"],
        [*ARGS, "--trios", "pal-mnk-ber,ber-mnk-pal"],
        [*ARGS, "--trios", ""],
        [*ARGS, "--parity-stride", "0"],
        [*ARGS, "--parity-stride", "3/50"],
        [*ARGS, "--parity-sample", "3/50"],  # (the offset is drawn from the snapshot id of the release: it is no option)
        [*ARGS, "--bogus"],
    ],
)
def test_arguments_that_are_wrong_end_the_command_with_a_message_and_status_2(script, recorded, capsys, bad):
    assert script.main(bad) == 2
    error = capsys.readouterr().err
    assert error.strip() and "Traceback" not in error
    assert recorded == []


def test_help_names_every_option(script, capsys):
    with pytest.raises(SystemExit) as stop:
        script.main(["--help"])
    assert stop.value.code == 0
    text = capsys.readouterr().out
    for option in ("--tag", "--privacy-key", "--processes", "--trios", "--catalog", "--previous", "--parity-stride", "--parity-processes", "--build-dir"):
        assert option in text
    assert not [option for option in ("--seen", "--wiki", "--client") if option in text]


def test_a_refused_release_ends_with_status_2_and_one_line(script, monkeypatch, capsys):
    def refuse(**kwargs):
        raise ReleaseRefused("the privacy scan found 3 findings in the release")

    monkeypatch.setattr(release, "build_release", refuse)
    assert script.main(ARGS) == 2
    captured = capsys.readouterr()
    assert captured.err == "refused: the privacy scan found 3 findings in the release\n" and "Traceback" not in captured.err


def test_a_failure_nobody_foresaw_ends_with_status_2_and_its_kind_and_a_traceback_only_on_request(script, monkeypatch, capsys):
    def crash(**kwargs):
        raise RuntimeError("something odd")

    monkeypatch.setattr(release, "build_release", crash)
    monkeypatch.delenv("TRIOFORGE_DEBUG", raising=False)
    assert script.main(ARGS) == 2
    assert capsys.readouterr().err == "error: RuntimeError: something odd\n"
    monkeypatch.setenv("TRIOFORGE_DEBUG", "1")
    assert script.main(ARGS) == 2
    assert "Traceback" in capsys.readouterr().err


def test_an_interrupt_says_that_a_run_again_resumes_and_ends_with_status_130(script, monkeypatch, capsys):
    def interrupted(**kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(release, "build_release", interrupted)
    assert script.main(ARGS) == 130
    assert "run it again" in capsys.readouterr().err


def test_a_solver_diff_is_said_loudly_and_a_stale_check_as_a_warning(script, monkeypatch, capsys):
    monkeypatch.setattr(release, "build_release", lambda **kw: result(solver_diffs=3, warnings=["the scheduled check sources-check has not run for 12 days (more than 10)"]))
    assert script.main(ARGS) == 0
    captured = capsys.readouterr()
    assert "SOLVER DIFF" in captured.err and "3" in captured.err and "results-diff" in captured.err and "a.md" in captured.err
    assert "warning: the scheduled check sources-check" in captured.err


SENTINEL_KEY = "w90417"  # an item key and a digest that the result of a build carries in places the summary must never print
SENTINEL_DIGEST = "5e" * 32


def test_the_summary_is_counts_and_paths_and_no_item_and_no_hash_of_a_flag(script, monkeypatch, capsys):
    outcome = SimpleNamespace(
        slug="pal-mnk-ber", status="done", notes=[f"{SENTINEL_KEY} was flagged"], violations=[f"{SENTINEL_KEY} {SENTINEL_DIGEST}"], error=SENTINEL_DIGEST
    )
    monkeypatch.setattr(
        release, "build_release", lambda **kw: result(outcomes=[outcome], seen_keys=[SENTINEL_KEY], seen_digest=SENTINEL_DIGEST, previous_keys=[SENTINEL_KEY])
    )
    assert script.main(ARGS) == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "data-2026-10-17.tar.gz" in out and "560 trios" in out and "12 changes" in out and ("ab" * 32) in out  # the digest of the asset: what is committed
    for text in (captured.out, captured.err):  # (the name of the test is the claim: neither the planted key nor the planted digest is anywhere in what is printed)
        assert SENTINEL_KEY not in text and SENTINEL_DIGEST not in text


def test_a_trial_build_says_that_it_wrote_no_pointer_and_nothing_in_the_tracked_folders(script, monkeypatch, capsys):
    monkeypatch.setattr(release, "build_release", lambda **kw: result(trial=True, pointer=None, trios=2))
    assert script.main([*ARGS, "--trios", "pal-mnk-ber,war-clr-pal"]) == 0
    out = capsys.readouterr().out
    assert "TRIAL" in out and "no pointer" in out and "commit it" not in out


def test_a_release_says_that_the_report_is_for_git_and_the_full_diff_is_not(script, monkeypatch, capsys):
    monkeypatch.setattr(release, "build_release", lambda **kw: result())
    assert script.main(ARGS) == 0
    out = capsys.readouterr().out
    assert "report: reports" in out and "full diff: " in out and "not for git" in out


def test_run_as_a_file_the_command_finds_the_package_without_a_path_set_for_it(tmp_path):
    environment = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    done = subprocess.run([sys.executable, str(SCRIPT), "--help"], cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "--privacy-key" in done.stdout


class ClosedPipe:
    """A standard output whose reader has gone: every write and flush fails as it does on a closed pipe."""

    def write(self, text):
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self):
        raise BrokenPipeError(32, "Broken pipe")


def test_a_pipe_that_closes_after_the_release_is_built_is_no_failure_and_a_warning_goes_to_standard_error(script, monkeypatch, capsys):
    monkeypatch.setattr(release, "build_release", lambda **kw: result())
    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    assert script.main(ARGS) == 0  # (the release is built and its outputs are written)
    assert "warning" in capsys.readouterr().err.lower()


def test_a_pipe_that_closes_is_no_failure_even_when_a_trial_or_a_solver_diff_has_more_to_say(script, monkeypatch, capsys):
    monkeypatch.setattr(release, "build_release", lambda **kw: result(trial=True, pointer=None, solver_diffs=2, warnings=["a stale check"]))
    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    assert script.main([*ARGS, "--trios", "pal-mnk-ber"]) == 0
    err = capsys.readouterr().err
    assert "SOLVER DIFF" in err and "a stale check" in err  # (what goes to standard error still does)


def test_a_standard_output_that_is_not_there_at_all_is_no_failure_of_a_release_that_was_built(capsys, monkeypatch):
    """Run as a file, as the maintainer's command is: with no standard output (``sys.stdout`` is None, as under pythonw) the final flush has nothing to flush, the exit
    status is 0, and what was not printed is said on standard error."""
    monkeypatch.setattr(release, "build_release", lambda **kw: (kw["say"]("a line of counts"), result())[1])
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *ARGS])
    monkeypatch.setattr(sys, "stdout", None)
    with pytest.raises(SystemExit) as stop:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert stop.value.code == 0
    err = capsys.readouterr().err
    assert "standard output was closed" in err and ("ab" * 32) in err  # (the digest of the asset is in it: the one thing the maintainer needs from the lines)


def test_a_line_that_the_console_cannot_encode_loses_the_character_and_not_the_lines_after_it(script, capsys, monkeypatch):
    """A console in an old code page (or a pipe with an ASCII encoding) cannot write every character of a path: the line is written with ``?`` for it, and the command goes on
    printing. Only a pipe that is really closed stops the printing."""
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="ascii", errors="strict", newline="\n", write_through=True)

    foreign = "".join(map(chr, (0xE9, 0x2192, 0xE9)))  # three characters that no ASCII encoding can write

    def build_in_a_folder_with_a_foreign_name(**kwargs):
        kwargs["say"](f"precompute: 36 chunks in a folder named {foreign}")
        return result(asset=Path(f"build/release/{foreign[:1]}.tar.gz"))

    monkeypatch.setattr(release, "build_release", build_in_a_folder_with_a_foreign_name)
    monkeypatch.setattr(sys, "stdout", console)
    assert script.main(ARGS) == 0
    lines = raw.getvalue().decode("ascii").splitlines()
    assert lines[0] == "precompute: 36 chunks in a folder named ???"
    assert lines[1].startswith("built data-2026-10-17: ") and re.fullmatch(r"asset: build.release.\?\.tar\.gz", lines[2])
    assert lines[3] == "sha256: " + "ab" * 32 and lines[4].startswith("pointer: ") and lines[-1].startswith("full diff: ")  # (every line after the first that could not be written)
    assert "standard output was closed" not in capsys.readouterr().err
