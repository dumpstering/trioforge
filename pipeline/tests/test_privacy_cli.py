"""Tests for the command line of the privacy scanner beyond the acceptance rows: modes,
git integration, catalog masking, history, identity and failure handling."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys

import pytest

from test_privacy_helpers import (  # noqa: F401  (fixtures are used by name)
    KEY_HEX,
    PIPELINE,
    ROOT,
    call_main,
    cli_env,
    commit,
    git,
    gitenv,
    h,
    keyfile,
    make_repo,
    parse_output,
    privacy_files,
    repo,
    run_cli,
    tag,
    write,
)
from trioforge.privacy import scan as S


def paths_and_rules(output):
    return [(f["path"], f["rule"]) for f in parse_output(output)]


# ---- usage ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [[], ["--all", "--staged"], ["--all", "f.txt"], ["--staged", "f.txt"], ["--bogus"]],
    ids=["no mode", "all and staged", "all and path", "staged and path", "unknown flag"],
)
def test_bad_usage_is_a_configuration_error(repo, keyfile, args):
    write(repo, "f.txt", "x\n")
    done = run_cli([*args, "--key-file", keyfile], repo)
    assert done.returncode == 2
    assert "Traceback" not in done.stderr


def test_an_empty_identity_address_is_a_configuration_error(repo):
    done = run_cli(["--identity", ""], repo)
    assert done.returncode == 2
    assert "identity" in done.stderr


def test_help_exits_cleanly(repo):
    done = run_cli(["--help"], repo)
    assert done.returncode == 0
    assert "--require-key" in done.stdout


# ---- --all ----------------------------------------------------------------------------------


def test_all_scans_tracked_files_as_the_index_holds_them_and_untracked_files_but_not_ignored(
    repo, keyfile
):
    write(repo, ".gitignore", "ignored/\n")
    write(repo, "tracked.txt", "clean\n")
    git(repo, "add", ".gitignore", "tracked.txt")
    commit(repo, "base")
    assert run_cli(["--all", "--key-file", keyfile], repo).returncode == 0

    write(repo, "ignored/leak.txt", "Zorblax\n")
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout  # an ignored file is not scanned

    write(repo, "untracked.txt", "Zorblax\n")
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert paths_and_rules(done.stdout) == [("untracked.txt", "denylist")]

    (repo / "untracked.txt").unlink()
    write(repo, "tracked.txt", "Zorblax\n")  # modified after the commit, not staged
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout  # a tracked file is read from the index, not the disk

    git(repo, "add", "tracked.txt")  # staged: the index holds it now
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert paths_and_rules(done.stdout) == [("tracked.txt", "denylist")]


def test_all_skips_tracked_files_that_are_deleted_from_the_working_tree(repo, keyfile):
    write(repo, "gone.txt", "clean\n")
    git(repo, "add", "gone.txt")
    commit(repo, "base")
    (repo / "gone.txt").unlink()
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout + done.stderr


def test_all_refuses_a_tracked_seen_flags_file_and_a_tracked_gitlink(repo, keyfile):
    write(repo, "derived/seen-flags.json", "[]\n")
    git(repo, "add", "-f", "derived/seen-flags.json")
    git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        "160000,1111111111111111111111111111111111111111,vendor/sub",
    )
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert sorted(paths_and_rules(done.stdout)) == [
        ("derived/seen-flags.json", "seen-flags"),
        ("vendor/sub", "submodule"),
    ]


def _try_symlink(link, target):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("this machine cannot create symbolic links")


def test_all_never_opens_untracked_non_regular_files_and_counts_them(repo, keyfile, tmp_path):
    secret = write(tmp_path, "outside/secret.txt", "Zorblax\n")
    _try_symlink(repo / "link.txt", secret)
    _try_symlink(repo / "dangling.txt", repo / "nowhere.txt")
    write(repo, "other.txt", "clean\n")
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout + done.stderr  # the link was not followed
    assert "skipped 2 non-regular" in done.stdout


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs on this platform")
def test_all_does_not_hang_on_a_tracked_file_that_became_a_fifo(repo, keyfile):
    # Git itself never lists an untracked FIFO, but a tracked path can be replaced by one, and
    # opening a FIFO with no writer would block forever.
    write(repo, "pipe", "it was a file\n")
    git(repo, "add", "pipe")
    commit(repo, "a file")
    (repo / "pipe").unlink()
    os.mkfifo(repo / "pipe")
    done = subprocess.run(
        [sys.executable, "-m", "trioforge.privacy.scan", "--all", "--key-file", str(keyfile)],
        cwd=repo,
        env=cli_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    # The tracked file is read from the index, so what is on disk is never opened.
    assert "non-regular" not in done.stdout


def test_a_symbolic_link_given_as_a_path_is_scanned_as_its_target_text_not_followed(
    repo, keyfile, tmp_path
):
    write(tmp_path, "outside/secret.txt", "Zorblax\n")
    _try_symlink(repo / "link.txt", "../outside/secret.txt")
    done = run_cli(["link.txt", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout + done.stderr  # the link text holds no name
    _try_symlink(repo / "zorblax-link.txt", "../outside/secret.txt")
    done = run_cli(["zorblax-link.txt", "--key-file", keyfile], repo)
    assert paths_and_rules(done.stdout) == [(f"[private:{tag('zorblax')}]-link.txt", "denylist")]


# ---- locked or unreadable files -------------------------------------------------------------


@contextlib.contextmanager
def locked(path):
    """Hold ``path`` so that nothing else can read it."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        handle = kernel32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
        assert handle != wintypes.HANDLE(-1).value, "could not lock the file"
        try:
            yield
        finally:
            kernel32.CloseHandle(handle)
    else:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root can read anything")
        os.chmod(path, 0)
        try:
            yield
        finally:
            os.chmod(path, 0o644)


def test_an_unreadable_file_is_a_configuration_error_with_a_masked_path(repo, keyfile):
    target = write(repo, "Zorblax-locked.txt", "clean\n")
    with locked(target):
        code, out, err = call_main(
            ["Zorblax-locked.txt", "--key-file", keyfile], cwd=repo, env={}
        )
    assert code == 2
    assert "cannot read file" in err
    assert "Traceback" not in err
    assert "zorblax" not in (out + err).lower()
    assert "[private:" in err


def test_a_missing_file_given_as_a_path_is_also_unreadable(repo, keyfile):
    done = run_cli(["no-such-file.txt", "--key-file", keyfile], repo)
    assert done.returncode == 2
    assert "cannot read file" in done.stderr


# ---- the catalog masks public game names ------------------------------------------------------

CATALOG = {
    "version": "test",
    "items": [
        {
            "name": "Cazic Thule Bracer",
            "sources": {"drops": [{"zone": "Plane of Fear", "npcs": ["Avatar of Fear"]}]},
        },
        {
            "name": "Bone Chips",
            "sources": {
                "drops": [{"zone": "Cazic Thule", "npcs": ["a skeleton", "Lord Cazic"]}],
                "sold_by": [{"npc": "Merchant Quimmet", "zone": "Qeynos"}],
            },
        },
    ],
}


def test_catalog_phrases_are_collected_from_names_zones_and_npcs(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(CATALOG), encoding="utf-8")
    phrases = S.load_catalog_phrases(str(path))
    assert {
        "Cazic Thule Bracer",
        "Plane of Fear",
        "Avatar of Fear",
        "Bone Chips",
        "Cazic Thule",
        "a skeleton",
        "Lord Cazic",
        "Merchant Quimmet",
        "Qeynos",
    } <= set(phrases)


def test_the_cli_masks_catalog_names_so_a_colliding_player_name_is_caught_elsewhere(repo, keyfile):
    privacy_files(repo, deny=("zorblax", "cazic"))
    write(repo, "derived/catalog.json", json.dumps(CATALOG))
    write(repo, "docs/a.md", "Drops in Cazic Thule and from Lord Cazic.\n")
    write(repo, "docs/b.md", "Cazic Thule is fine but Cazic alone is not.\n")
    ok = run_cli(["docs/a.md", "--key-file", keyfile], repo)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = run_cli(["docs/b.md", "--key-file", keyfile], repo)
    assert bad.returncode == 1
    found = parse_output(bad.stdout)
    assert [(f["line"], f["col"], f["rule"]) for f in found] == [("1", "25", "denylist")]
    assert "cazic" not in bad.stdout.lower()


def test_a_broken_catalog_is_a_configuration_error(repo, keyfile):
    write(repo, "derived/catalog.json", "{ not json")
    write(repo, "docs/a.md", "text\n")
    done = run_cli(["docs/a.md", "--key-file", keyfile], repo)
    assert done.returncode == 2
    assert "catalog" in done.stderr


def test_the_allow_file_silences_reviewed_harmless_tokens(repo, keyfile):
    privacy_files(repo, deny=("zorblax", "quimmet"), allow=("quimmet",))
    write(repo, "docs/a.md", "Quimmet waves\n")
    assert run_cli(["docs/a.md", "--key-file", keyfile], repo).returncode == 0
    write(repo, "docs/b.md", "Quimmet and Zorblax\n")
    done = run_cli(["docs/b.md", "--key-file", keyfile], repo)
    assert done.returncode == 1 and len(parse_output(done.stdout)) == 1


def test_a_missing_denylist_file_fails_only_when_the_key_is_required(repo, keyfile):
    (repo / "privacy" / "denylist.hmac").unlink()
    write(repo, "docs/a.md", "text\n")
    required = run_cli(["docs/a.md", "--require-key", "--key-file", keyfile], repo)
    assert required.returncode == 2 and "denylist" in required.stderr
    relaxed = run_cli(["docs/a.md", "--key-file", keyfile], repo)
    assert relaxed.returncode == 0 and "denylist check skipped" in relaxed.stdout


def test_a_malformed_line_exception_file_is_a_configuration_error(repo, keyfile):
    write(repo, "privacy/allowlist-lines.txt", "# header\nonly-one-field\n")
    write(repo, "docs/a.md", "text\n")
    done = run_cli(["docs/a.md", "--key-file", keyfile], repo)
    assert done.returncode == 2
    assert "allowlist-lines" in done.stderr


# ---- paths: absolute, directories, normalization -----------------------------------------------


def test_an_absolute_path_inside_the_repository_matches_its_relative_line_exception(repo, keyfile):
    import hashlib

    line = "You have " + "looted a Rusty Dagger."
    entry = ("docs/x.md", "log-loot", hashlib.sha256(line.encode()).hexdigest())
    privacy_files(repo, allow_lines=[entry])
    target = write(repo, "docs/x.md", line + "\n")
    done = run_cli([str(target), "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_directory_argument_is_walked(repo, keyfile):
    write(repo, "docs/a.md", "clean\n")
    write(repo, "docs/deep/b.md", "Zorblax\n")
    done = run_cli(["docs", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert paths_and_rules(done.stdout) == [("docs/deep/b.md", "denylist")]


# ---- commit messages ----------------------------------------------------------------------------


def test_commit_msg_scans_comment_lines_and_below_the_scissors_line_alike(repo, keyfile):
    scissors = "# " + "-" * 24 + " >8 " + "-" * 24
    write(repo, "m1.txt", f"fix a thing\n\n{scissors}\n-removed Zorblax line\n")
    below = run_cli(["--commit-msg", "m1.txt", "--key-file", keyfile], repo)
    assert below.returncode == 1, below.stdout + below.stderr
    assert [(f["path"], f["line"]) for f in parse_output(below.stdout)] == [("<commit-msg>", "4")]
    write(repo, "m2.txt", "fix a thing\n# a comment about Zorblax\n")
    bad = run_cli(["--commit-msg", "m2.txt", "--key-file", keyfile], repo)
    assert bad.returncode == 1
    assert [(f["path"], f["line"]) for f in parse_output(bad.stdout)] == [("<commit-msg>", "2")]


def test_commit_msg_checks_log_shapes_too(repo, keyfile):
    write(repo, "m.txt", "paste:\n" + "You have " + "looted a thing\n")
    done = run_cli(["--commit-msg", "m.txt", "--key-file", keyfile], repo)
    assert paths_and_rules(done.stdout) == [("<commit-msg>", "log-loot")]


def test_commit_msg_with_a_missing_file_is_a_configuration_error(repo, keyfile):
    done = run_cli(["--commit-msg", "nope.txt", "--key-file", keyfile], repo)
    assert done.returncode == 2 and "cannot read file" in done.stderr


# ---- history --------------------------------------------------------------------------------------


def test_history_covers_tag_names_annotated_tag_messages_and_paths_of_deleted_files(repo, keyfile):
    write(repo, "notes/zorblax.md", "clean\n")
    git(repo, "add", "notes/zorblax.md")
    commit(repo, "base")
    git(repo, "rm", "-q", "notes/zorblax.md")
    commit(repo, "drop")
    git(repo, "tag", "release-quimmet")
    git(repo, "tag", "-a", "-m", "notes about Zorblax", "v1")
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    found = parse_output(done.stdout)
    assert all(f["rule"] == "denylist" for f in found)
    kinds = sorted(f["path"].split(":")[0].split("/")[0] for f in found)
    assert len(found) == 3, found
    assert "zorblax" not in (done.stdout + done.stderr).lower()
    assert "quimmet" not in (done.stdout + done.stderr).lower()
    assert kinds.count("<ref") == 1


def test_history_applies_the_log_shape_rules_to_messages_and_blobs(repo, keyfile):
    write(repo, "paste.txt", "x\n" + "You have " + "looted a thing\n")
    git(repo, "add", "paste.txt")
    commit(repo, "msg\n\n" + "You have " + "looted a thing")
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert sorted(f["rule"] for f in parse_output(done.stdout)) == ["log-loot", "log-loot"]


def test_history_without_a_key_runs_the_log_rules_and_says_so(repo):
    write(repo, "paste.txt", "x\n" + "You have " + "looted a thing\n")
    git(repo, "add", "paste.txt")
    commit(repo, "base")
    code, out, err = call_main(["--history"], cwd=repo)
    assert code == 1 and "denylist check skipped (no key)" in out


def test_history_scans_binary_blobs_with_the_strings_pass(repo, keyfile):
    write(repo, "blob.bin", b"\x00\x01\x02Zorblax\x00\x03")
    git(repo, "add", "blob.bin")
    commit(repo, "binary")
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert paths_and_rules(done.stdout) == [("blob.bin", "denylist")]


def test_history_reports_a_blob_once_however_many_commits_contain_it(repo, keyfile):
    for number in range(3):
        write(repo, "leak.txt", "Zorblax\n")
        write(repo, "n.txt", f"{number}\n")
        git(repo, "add", "leak.txt", "n.txt")
        commit(repo, f"round {number}")
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert paths_and_rules(done.stdout) == [("leak.txt", "denylist")]


# ---- identity -------------------------------------------------------------------------------------


def test_identity_flags_a_foreign_committer_address_once_per_commit(repo):
    write(repo, "a.txt", "x\n")
    git(repo, "add", "a.txt")
    env = dict(os.environ, GIT_COMMITTER_EMAIL="other@example.com")
    git(repo, "-c", "user.email=maintainers@trioforge.invalid", "commit", "-q", "-m", "one", env=env)
    done = run_cli(["--identity", "maintainers@trioforge.invalid"], repo)
    assert done.returncode == 1
    assert [f["rule"] for f in parse_output(done.stdout)] == ["identity"]
    assert "other@example.com" not in done.stdout + done.stderr


def test_identity_compares_addresses_ignoring_case_and_checks_every_branch(repo):
    git(repo, "config", "user.email", "Maintainers@TrioForge.invalid")
    write(repo, "a.txt", "x\n")
    git(repo, "add", "a.txt")
    commit(repo, "one")
    git(repo, "checkout", "-q", "-b", "side")
    write(repo, "b.txt", "y\n")
    git(repo, "add", "b.txt")
    git(repo, "-c", "user.email=intruder@example.com", "commit", "-q", "-m", "two")
    git(repo, "checkout", "-q", "main")
    done = run_cli(["--identity", "maintainers@trioforge.invalid"], repo)
    assert done.returncode == 1
    assert len(parse_output(done.stdout)) == 1  # only the commit on the side branch


def test_identity_flags_the_tagger_of_an_annotated_tag(repo):
    git(repo, "config", "user.email", "maintainers@trioforge.invalid")
    write(repo, "a.txt", "x\n")
    git(repo, "add", "a.txt")
    commit(repo, "one")
    git(repo, "-c", "user.email=tagger@example.com", "tag", "-a", "-m", "release", "v1")
    done = run_cli(["--identity", "maintainers@trioforge.invalid"], repo)
    assert done.returncode == 1
    assert "tagger@example.com" not in done.stdout + done.stderr


def test_identity_on_an_empty_repository_passes(repo):
    assert run_cli(["--identity", "maintainers@trioforge.invalid"], repo).returncode == 0


# ---- staged scans of unusual content ---------------------------------------------------------------


def test_staged_binary_files_get_the_strings_pass(repo, keyfile):
    write(repo, "blob.bin", b"\x00\x01\x02Zorblax\x00\x03")
    git(repo, "add", "blob.bin")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert paths_and_rules(done.stdout) == [("blob.bin", "denylist")]


def test_staged_renames_and_copies_are_scanned_under_their_new_name(repo, keyfile):
    write(repo, "old.txt", "clean content that is long enough to be a rename\n" * 5)
    git(repo, "add", "old.txt")
    commit(repo, "base")
    git(repo, "mv", "old.txt", "zorblax-new.txt")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert paths_and_rules(done.stdout) == [(f"[private:{tag('zorblax')}]-new.txt", "denylist")]


def test_staged_scan_of_the_very_first_commit_works(repo, keyfile):
    write(repo, "a.txt", "Zorblax\n")
    git(repo, "add", "a.txt")
    assert run_cli(["--staged", "--key-file", keyfile], repo).returncode == 1


def test_the_scan_runs_from_a_subdirectory_of_the_repository(repo, keyfile):
    write(repo, "sub/dir/f.txt", "Zorblax\n")
    git(repo, "add", "sub/dir/f.txt")
    done = run_cli(["--staged", "--key-file", keyfile], repo / "sub" / "dir")
    assert done.returncode == 1
    assert paths_and_rules(done.stdout) == [("sub/dir/f.txt", "denylist")]


# ---- failure handling -------------------------------------------------------------------------------


def test_an_unexpected_error_prints_one_line_and_exits_2(repo, keyfile, monkeypatch):
    write(repo, "f.txt", "x\n")

    def explode(*args, **kwargs):
        raise RuntimeError("secret detail Zorblax")

    monkeypatch.setattr(S, "scan_paths", explode)
    code, out, err = call_main(["f.txt", "--key-file", keyfile], cwd=repo)
    assert code == 2
    assert err.strip().count("\n") == 0
    assert "RuntimeError" in err and "zorblax" not in (out + err).lower()


def test_non_ascii_paths_never_crash_the_output(repo, keyfile):
    name = "caf\u00e9-\u4e2d.txt"
    write(repo, name, "You have " + "looted a thing\n")
    env = cli_env()
    env.pop("PYTHONUTF8")
    env.pop("PYTHONIOENCODING")
    env["PYTHONLEGACYWINDOWSSTDIO"] = "1"
    done = subprocess.run(
        [sys.executable, "-m", "trioforge.privacy.scan", name, "--key-file", str(keyfile)],
        cwd=repo,
        env=env,
        capture_output=True,
    )
    assert done.returncode == 1, done.stderr
    assert b"Traceback" not in done.stderr
    assert b"log-loot" in done.stdout


def test_the_module_can_be_run_with_python_dash_m(repo, keyfile):
    write(repo, "f.txt", "clean\n")
    done = subprocess.run(
        [sys.executable, "-m", "trioforge.privacy.scan", "f.txt", "--key-file", str(keyfile)],
        cwd=repo,
        env=cli_env(),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0 and "privacy scan: 1 files, 0 findings" in done.stdout


# ---- the repository passes its own scanner -----------------------------------------------------------


def test_the_repository_passes_its_own_log_shape_rules():
    """Step 4 of the plan: ``scan --all`` over this repository exits 0 (here without the key,
    so only the log-shape rules and path rules run; CI runs the keyed scan)."""
    code, out, err = call_main(["--all"], cwd=ROOT, env={})
    assert code == 0, out + err
    assert "denylist check skipped (no key)" in out


def test_history_checks_every_path_that_ever_existed_even_when_a_blob_has_two_names(repo, keyfile):
    # Both names point at one blob; `git rev-list --objects` prints only one of them.
    write(repo, "a-notes.txt", "same content\n")
    write(repo, "zorblax-notes.txt", "same content\n")
    git(repo, "add", "a-notes.txt", "zorblax-notes.txt")
    commit(repo, "two names")
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert paths_and_rules(done.stdout) == [(f"[private:{tag('zorblax')}]-notes.txt", "denylist")]


# ---- more failure handling and git environment ---------------------------------------------------------


def test_an_unreadable_denylist_is_a_configuration_error_that_names_the_file(repo, keyfile):
    write(repo, "docs/a.md", "text\n")
    with locked(repo / "privacy" / "denylist.hmac"):
        code, out, err = call_main(["docs/a.md", "--key-file", keyfile], cwd=repo, env={})
    assert code == 2
    assert err.strip() == "cannot read file: privacy/denylist.hmac"


def test_commit_msg_reads_crlf_files_and_counts_lines(repo, keyfile):
    (repo / "m.txt").write_bytes(b"fix the thing\r\nthanks Zorblax\r\n")
    done = run_cli(["--commit-msg", "m.txt", "--key-file", keyfile], repo)
    assert [(f["path"], f["line"], f["col"]) for f in parse_output(done.stdout)] == [
        ("<commit-msg>", "2", "8")
    ]


def test_staged_scan_follows_git_index_file_like_a_partial_commit_does(repo, keyfile, monkeypatch):
    write(repo, "leak.txt", "Zorblax\n")
    git(repo, "add", "leak.txt")  # the real index holds a leak ...
    write(repo, "fine.txt", "nothing\n")
    alternate = repo / ".git" / "alternate-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate))
    git(repo, "add", "fine.txt")  # ... the alternate index (git commit <paths> uses one) does not
    code, out, err = call_main(["--staged", "--key-file", keyfile], cwd=repo, env={})
    assert code == 0, out + err
    assert "1 files, 0 findings" in out


def test_non_ascii_file_names_are_scanned_and_printed(repo, keyfile):
    name = "caf" + chr(0xE9) + ".txt"
    write(repo, name, "Zorblax\n")
    code, out, err = call_main(["--all", "--key-file", keyfile], cwd=repo, env={})
    assert code == 1
    assert [(f["path"], f["rule"]) for f in parse_output(out)] == [(name, "denylist")]


def test_a_missing_object_in_history_is_an_error_not_a_clean_scan(repo, keyfile):
    import stat

    write(repo, "a.txt", "some content\n")
    git(repo, "add", "a.txt")
    commit(repo, "one")
    oid = git(repo, "rev-parse", "HEAD:a.txt").stdout.decode().strip()
    loose = repo / ".git" / "objects" / oid[:2] / oid[2:]
    loose.chmod(stat.S_IWRITE | stat.S_IREAD)
    loose.unlink()
    code, out, err = call_main(["--history", "--key-file", keyfile], cwd=repo, env={})
    assert code == 2, out + err
    assert "Traceback" not in err and len(err.strip().splitlines()) == 1
