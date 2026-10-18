"""Tests for the scanner's use of git and for its command line: reading objects without being
fooled, who made a commit and when, what a push is about to send, which files count, and what is
printed.

Test data is invented. Strings shaped like log lines are built at run time (see
``test_privacy_helpers``), and no non-ASCII character is written out in this file.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys

import pytest

from test_privacy_helpers import (  # noqa: F401  (fixtures are used by name)
    HEADER_ALLOW,
    HEADER_DENY,
    KEY_HEX,
    call_main,
    commit,
    git,
    gitenv,
    h,
    key_check,
    keyfile,
    loot_line,
    make_repo,
    parse_output,
    privacy_files,
    repo,
    run_cli,
    tag,
    write,
)
from trioforge.privacy import gitio
from trioforge.privacy import scan as S

ALLOWED = "maintainers@trioforge.invalid"
ZERO = "0" * 40
IN_ANOTHER_ZONE = "2026-10-13T12:00:00-0500"


def head(repo) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.decode().strip()


def commit_as(
    repo,
    message="work",
    *,
    name="Test User",
    email=ALLOWED,
    committer_name=None,
    committer_email=None,
    author_date=None,
    committer_date=None,
) -> str:
    """An empty commit with the given people and dates; returns its id."""
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME=name,
        GIT_AUTHOR_EMAIL=email,
        GIT_COMMITTER_NAME=committer_name or name,
        GIT_COMMITTER_EMAIL=committer_email or email,
    )
    if author_date:
        env["GIT_AUTHOR_DATE"] = author_date
    if committer_date:
        env["GIT_COMMITTER_DATE"] = committer_date
    git(repo, "commit", "-q", "--allow-empty", "-m", message, env=env)
    return head(repo)


def found(done):
    return [(f["path"], f["rule"]) for f in parse_output(done.stdout)]


def abbreviated(repo, rev="HEAD") -> str:
    return git(repo, "log", "-1", "--format=%h", rev).stdout.decode().strip()


# ---- git is read without being fooled, and a failure is never a clean result -----------------


class FakeProcess:
    """Stands in for the long-lived ``git cat-file --batch`` process."""

    def __init__(self, output: bytes, returncode: int = 0) -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(output)
        self.returncode = returncode

    def wait(self):
        return self.returncode


def batch_with(monkeypatch, repo, output: bytes, returncode: int = 0):
    monkeypatch.setattr(gitio.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(output, returncode))
    return gitio.BatchReader(gitio.Git(str(repo)))


OID = "a" * 40


def test_a_short_read_from_the_object_stream_is_an_error(repo, monkeypatch):
    batch = batch_with(monkeypatch, repo, OID.encode() + b" blob 10\nabc")
    _kind, blob = batch.get(OID)
    with pytest.raises(gitio.ScanError, match="truncated"):
        blob.read()


def test_a_short_read_in_the_middle_of_an_object_is_an_error_too(repo, monkeypatch):
    batch = batch_with(monkeypatch, repo, OID.encode() + b" blob 6\nabcd")
    _kind, blob = batch.get(OID)
    assert blob.read(2) == b"ab"
    with pytest.raises(gitio.ScanError, match="truncated"):
        blob.read(4)


def test_a_batch_process_that_fails_is_an_error_when_it_is_closed(repo, monkeypatch):
    batch = batch_with(monkeypatch, repo, OID.encode() + b" blob 3\nabc\n", returncode=128)
    _kind, blob = batch.get(OID)
    assert blob.read() == b"abc"
    with pytest.raises(gitio.ScanError, match="cat-file"):
        batch.close()


def test_a_batch_process_that_succeeds_closes_quietly(repo, monkeypatch):
    batch = batch_with(monkeypatch, repo, OID.encode() + b" blob 3\nabc\n", returncode=0)
    _kind, blob = batch.get(OID)
    assert blob.read() == b"abc"
    batch.close()


def test_closing_after_another_error_does_not_replace_that_error(repo, monkeypatch):
    batch = batch_with(monkeypatch, repo, b"", returncode=128)
    with pytest.raises(KeyError):
        with batch:
            raise KeyError("the first error")


def test_a_truncated_object_stream_ends_the_scan_with_exit_code_2(repo, keyfile, monkeypatch):
    write(repo, "a.txt", "some text that is longer than a few bytes\n")
    git(repo, "add", "a.txt")
    commit(repo, "one")
    original = gitio.BatchReader._take

    def short(self, size):
        data = original(self, size)
        return data[: len(data) // 2] if size > 4 else data

    monkeypatch.setattr(gitio.BatchReader, "_take", short)
    code, out, err = call_main(["--history", "--key-file", keyfile], cwd=repo)
    assert code == 2, out + err
    assert "truncated" in err and "Traceback" not in err and len(err.strip().splitlines()) == 1


def test_every_git_call_is_made_with_the_safe_options(repo, keyfile, monkeypatch):
    write(repo, "a.txt", "clean\n")
    git(repo, "add", "a.txt")
    commit(repo, "one")
    write(repo, "b.txt", "clean too\n")
    git(repo, "add", "b.txt")
    calls = []
    real_run, real_popen = subprocess.run, subprocess.Popen

    def run(argv, *args, **kwargs):
        calls.append((list(argv), kwargs.get("env")))
        return real_run(argv, *args, **kwargs)

    class Popen(real_popen):
        def __init__(self, argv, *args, **kwargs):
            calls.append((list(argv), kwargs.get("env")))
            super().__init__(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", Popen)
    for flags in (["--staged"], ["--all"], ["--history"], ["--identity", ALLOWED]):
        call_main([*flags, "--key-file", keyfile], cwd=repo)
    assert len(calls) > 8
    for argv, env in calls:
        # Replacement objects are never used, and paths are never quoted.
        assert argv[1:4] == ["--no-replace-objects", "-c", "core.quotepath=false"], argv
        assert env is not None and env.get("GIT_NO_REPLACE_OBJECTS") == "1", argv


def _replace(repo, original: str, replacement: str):
    git(repo, "replace", original, replacement)


def test_a_replaced_blob_in_history_is_scanned_as_it_really_is(repo, keyfile):
    write(repo, "leak.txt", "Zorblax\n")
    git(repo, "add", "leak.txt")
    commit(repo, "add")
    leak = git(repo, "rev-parse", "HEAD:leak.txt").stdout.decode().strip()
    clean = git(repo, "hash-object", "-w", "--stdin", input=b"clean\n").stdout.decode().strip()
    _replace(repo, leak, clean)
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert ("leak.txt", "denylist") in found(done)


def test_a_replaced_staged_blob_is_scanned_as_it_really_is(repo, keyfile):
    write(repo, "leak.txt", "Zorblax\n")
    git(repo, "add", "leak.txt")
    leak = git(repo, "rev-parse", ":leak.txt").stdout.decode().strip()
    clean = git(repo, "hash-object", "-w", "--stdin", input=b"clean\n").stdout.decode().strip()
    _replace(repo, leak, clean)
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert found(done) == [("leak.txt", "denylist")]


def test_a_replaced_commit_message_is_scanned_as_it_really_is(repo, keyfile):
    base = commit_as(repo, "base")
    git(repo, "checkout", "-q", "-b", "side")
    leaky = commit_as(repo, "thanks Zorblax")
    git(repo, "checkout", "-q", "main")
    _replace(repo, leaky, base)
    done = run_cli(["--history", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert any(rule == "denylist" and path.startswith("<commit:") for path, rule in found(done))
    assert "zorblax" not in (done.stdout + done.stderr).lower()


# ---- identity: who made a commit, under what name, and in which time zone --------------------


def test_an_email_with_a_tab_in_it_is_an_identity_finding_not_a_skipped_record(repo):
    email = ALLOWED.replace("@", chr(9) + "@")
    commit_as(repo, email=email)
    done = run_cli(["--identity", ALLOWED], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert found(done) == [(f"<commit:{abbreviated(repo)}>", "identity")]
    assert chr(9) not in done.stdout


def test_an_unreadable_identity_record_is_a_finding(repo, monkeypatch):
    commit_as(repo)
    real = S.Git.run

    def cut_short(self, *args, **kwargs):
        output = real(self, *args, **kwargs)
        return output[: len(output) // 2] if args and args[0] == "log" else output

    monkeypatch.setattr(S.Git, "run", cut_short)
    code, out, err = call_main(["--identity", ALLOWED], cwd=repo)
    assert code == 1, out + err
    assert [f["rule"] for f in parse_output(out)] == ["identity"]


def test_an_author_name_that_is_on_the_denylist_is_a_finding(repo, keyfile):
    commit_as(repo, name="Zorblax Quimmet")
    done = run_cli(["--identity", ALLOWED, "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    rows = parse_output(done.stdout)
    assert [f["rule"] for f in rows] == ["denylist", "denylist"]
    assert all(f["path"] == f"<commit:{abbreviated(repo)}>" for f in rows)
    assert {f["tag"] for f in rows} == {tag("zorblax"), tag("quimmet")}
    assert "zorblax" not in (done.stdout + done.stderr).lower()


def test_a_committer_name_that_is_on_the_denylist_is_a_finding(repo, keyfile):
    commit_as(repo, committer_name="Zorblax")
    done = run_cli(["--identity", ALLOWED, "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert [f["rule"] for f in parse_output(done.stdout)] == ["denylist"]


def test_a_tagger_name_that_is_on_the_denylist_is_a_finding(repo, keyfile):
    commit_as(repo)
    env = dict(os.environ, GIT_COMMITTER_NAME="Zorblax", GIT_COMMITTER_EMAIL=ALLOWED)
    git(repo, "tag", "-a", "-m", "release", "v1", env=env)
    done = run_cli(["--identity", ALLOWED, "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert found(done) == [("<ref:refs/tags/v1>", "denylist")]


def test_a_name_shaped_like_a_log_line_is_a_finding_even_without_the_key(repo):
    commit_as(repo, name=loot_line())
    code, out, err = call_main(["--identity", ALLOWED], cwd=repo)
    assert code == 1, out + err
    assert [f["rule"] for f in parse_output(out)] == ["log-loot"]


@pytest.mark.parametrize("which", ["author", "committer"])
@pytest.mark.parametrize("date", [IN_ANOTHER_ZONE, "2026-10-13T12:00:00+0100"])
def test_a_commit_dated_outside_utc_is_a_timezone_finding(repo, which, date):
    commit_as(
        repo,
        author_date=date if which == "author" else None,
        committer_date=date if which == "committer" else None,
    )
    done = run_cli(["--identity", ALLOWED], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert found(done) == [(f"<commit:{abbreviated(repo)}>", "timezone")]
    assert "0500" not in done.stdout and "0100" not in done.stdout


def test_a_commit_dated_in_utc_passes_the_timezone_check(repo):
    commit_as(repo, author_date="2026-10-13T12:00:00+0000", committer_date="2026-10-13T12:00:00+0000")
    assert run_cli(["--identity", ALLOWED], repo).returncode == 0


def test_a_tag_dated_outside_utc_is_a_timezone_finding(repo, keyfile):
    commit_as(repo)
    env = dict(os.environ, GIT_COMMITTER_DATE=IN_ANOTHER_ZONE, GIT_COMMITTER_EMAIL=ALLOWED)
    git(repo, "tag", "-a", "-m", "release", "v1", env=env)
    done = run_cli(["--identity", ALLOWED, "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert found(done) == [("<ref:refs/tags/v1>", "timezone")]


# ---- the expected address comes from a committed file --------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        ALLOWED.encode() + b"\n",
        ALLOWED.encode(),
        ALLOWED.encode() + b"\r\n",
        b"\xef\xbb\xbf" + ALLOWED.encode() + b"\r\n",
        b"  " + ALLOWED.encode() + b"  \n\n",
    ],
    ids=["newline", "bare", "crlf", "bom and crlf", "padded"],
)
def test_the_identity_file_may_carry_a_bom_a_line_ending_and_spaces(repo, content):
    write(repo, "privacy/identity.txt", content)
    commit_as(repo)
    done = run_cli(["--identity-file", "privacy/identity.txt"], repo)
    assert done.returncode == 0, done.stdout + done.stderr


def test_commits_are_checked_against_the_file_not_against_git_config(repo):
    write(repo, "privacy/identity.txt", ALLOWED + "\n")
    git(repo, "config", "user.email", "someone@example.invalid")
    commit_as(repo, email="someone@example.invalid")
    done = run_cli(["--identity-file", "privacy/identity.txt"], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert found(done) == [(f"<commit:{abbreviated(repo)}>", "identity")]
    assert "someone@example.invalid" not in done.stdout + done.stderr


@pytest.mark.parametrize(
    "content",
    [b"", b"\n", b"no-at-sign\n", b"a@b.invalid\nc@d.invalid\n", b"a b@c.invalid\n", b"@c.invalid\n"],
    ids=["empty", "blank", "no at sign", "two lines", "a space", "no name"],
)
def test_an_identity_file_that_is_not_one_address_is_a_configuration_error(repo, content):
    write(repo, "privacy/identity.txt", content)
    done = run_cli(["--identity-file", "privacy/identity.txt"], repo)
    assert done.returncode == 2, done.stdout + done.stderr
    assert "identity file" in done.stderr and "Traceback" not in done.stderr


def test_a_missing_identity_file_is_a_configuration_error(repo):
    done = run_cli(["--identity-file", "privacy/nothing.txt"], repo)
    assert done.returncode == 2
    assert "identity file" in done.stderr


def test_an_address_and_an_identity_file_cannot_be_given_together(repo):
    write(repo, "privacy/identity.txt", ALLOWED + "\n")
    done = run_cli(["--identity", ALLOWED, "--identity-file", "privacy/identity.txt"], repo)
    assert done.returncode == 2
    assert "usage error" in done.stderr


# ---- a push is checked for what it is about to send ----------------------------------------------


def push_line(local_ref, local_sha, remote_ref, remote_sha=ZERO) -> str:
    return f"{local_ref} {local_sha} {remote_ref} {remote_sha}\n"


def pre_push(repo, keyfile, lines, remote="origin", *more):
    return call_main(
        ["--pre-push", remote, "--key-file", keyfile, "--require-key", *more], cwd=repo, stdin=lines
    )


def test_a_push_of_clean_commits_passes(repo, keyfile):
    write(repo, "a.txt", "clean\n")
    git(repo, "add", "a.txt")
    commit(repo, "work")
    code, out, err = pre_push(repo, keyfile, push_line("refs/heads/main", head(repo), "refs/heads/main"))
    assert code == 0, out + err


def test_a_push_that_sends_a_leak_in_a_new_commit_is_blocked(repo, keyfile):
    write(repo, "leak.txt", "Zorblax\n")
    git(repo, "add", "leak.txt")
    commit(repo, "work")
    code, out, err = pre_push(repo, keyfile, push_line("refs/heads/main", head(repo), "refs/heads/main"))
    assert code == 1, out + err
    assert [(f["path"], f["rule"]) for f in parse_output(out)] == [("leak.txt", "denylist")]


def test_a_remote_tag_named_with_a_denylisted_token_is_blocked(repo, keyfile):
    commit_as(repo)
    line = push_line("refs/heads/main", head(repo), "refs/tags/zorblax-v1")
    code, out, err = pre_push(repo, keyfile, line)
    assert code == 1, out + err
    assert [(f["path"], f["rule"]) for f in parse_output(out)] == [
        (f"<ref:refs/tags/[private:{tag('zorblax')}]-v1>", "denylist")
    ]
    assert "zorblax" not in (out + err).lower()


def test_a_commit_that_no_branch_or_tag_reaches_is_scanned_when_it_is_pushed_by_id(repo, keyfile):
    write(repo, "a.txt", "clean\n")
    git(repo, "add", "a.txt")
    commit(repo, "base")
    write(repo, "leak.txt", "Zorblax\n")
    git(repo, "add", "leak.txt")
    commit(repo, "oops")
    lost = head(repo)
    git(repo, "reset", "-q", "--hard", "HEAD~1")  # only the reflog remembers it now
    # Scanning every branch and tag does not see it ...
    assert run_cli(["--history", "--key-file", keyfile], repo).returncode == 0
    # ... but a push of that commit by its id does.
    code, out, err = pre_push(repo, keyfile, push_line(lost, lost, "refs/heads/elsewhere"))
    assert code == 1, out + err
    assert [(f["path"], f["rule"]) for f in parse_output(out)] == [("leak.txt", "denylist")]


def test_deleting_a_remote_ref_is_not_blocked_by_the_name_of_that_ref(repo, keyfile):
    commit_as(repo)
    line = push_line("(delete)", ZERO, "refs/tags/zorblax-v1", head(repo))
    code, out, err = pre_push(repo, keyfile, line)
    assert code == 0, out + err


def test_only_the_commits_the_remote_lacks_are_scanned_for_a_branch_it_has(repo, keyfile):
    write(repo, "leak.txt", "Zorblax\n")
    git(repo, "add", "leak.txt")
    commit(repo, "old")
    old = head(repo)
    git(repo, "rm", "-q", "leak.txt")
    commit(repo, "clean up")
    new = head(repo)
    # The remote already holds the old commit: only what comes after it is sent.
    code, out, err = pre_push(repo, keyfile, push_line("refs/heads/main", new, "refs/heads/main", old))
    assert code == 0, out + err
    # A new branch on the remote sends everything.
    code, out, err = pre_push(repo, keyfile, push_line("refs/heads/main", new, "refs/heads/main"))
    assert code == 1, out + err


def test_commits_that_a_remote_tracking_branch_already_holds_are_not_sent_again(repo, keyfile):
    write(repo, "leak.txt", "Zorblax\n")
    git(repo, "add", "leak.txt")
    commit(repo, "old")
    git(repo, "update-ref", "refs/remotes/origin/main", head(repo))
    git(repo, "rm", "-q", "leak.txt")
    commit(repo, "clean up")
    line = push_line("refs/heads/main", head(repo), "refs/heads/feature")
    assert pre_push(repo, keyfile, line, "origin")[0] == 0
    assert pre_push(repo, keyfile, line, "upstream")[0] == 1  # another remote holds nothing


def test_a_remote_commit_that_is_not_known_here_counts_as_a_new_branch(repo, keyfile):
    write(repo, "leak.txt", "Zorblax\n")
    git(repo, "add", "leak.txt")
    commit(repo, "old")
    line = push_line("refs/heads/main", head(repo), "refs/heads/main", "1" * 40)
    code, out, err = pre_push(repo, keyfile, line)
    assert code == 1, out + err


def test_the_commits_of_a_push_are_checked_for_who_made_them_when_an_identity_is_given(repo, keyfile):
    write(repo, "privacy/identity.txt", ALLOWED + "\n")
    commit_as(repo, email="someone@example.invalid")
    line = push_line("refs/heads/main", head(repo), "refs/heads/main")
    code, out, err = pre_push(repo, keyfile, line, "origin", "--identity-file", "privacy/identity.txt")
    assert code == 1, out + err
    assert [f["rule"] for f in parse_output(out)] == ["identity"]
    assert "someone@example.invalid" not in out + err


@pytest.mark.parametrize(
    "lines",
    [
        "refs/heads/main " + "a" * 40 + " refs/heads/main\n",
        "refs/heads/main xyz refs/heads/main " + ZERO + "\n",
        "refs/heads/main " + "a" * 40 + " refs/heads/main " + ZERO + " extra\n",
    ],
    ids=["three fields", "not an object id", "five fields"],
)
def test_malformed_push_input_is_a_configuration_error(repo, keyfile, lines):
    code, out, err = pre_push(repo, keyfile, lines)
    assert code == 2, out + err
    assert "pre-push input" in err and "Traceback" not in err


def test_a_remote_name_that_looks_like_an_option_is_a_configuration_error(repo, keyfile):
    commit_as(repo)
    code, out, err = pre_push(
        repo, keyfile, push_line("refs/heads/main", head(repo), "refs/heads/main"), "--exec=evil"
    )
    assert code == 2, out + err


def test_an_empty_push_input_scans_nothing_and_passes(repo, keyfile):
    code, out, err = pre_push(repo, keyfile, "")
    assert code == 0, out + err


# ---- m1: the whole commit message is scanned ----------------------------------------------------


def test_commit_msg_scans_below_the_scissors_line_too(repo, keyfile):
    scissors = "# " + "-" * 24 + " >8 " + "-" * 24
    write(repo, "m1.txt", f"fix a thing\n\n{scissors}\n-removed Zorblax line\n")
    done = run_cli(["--commit-msg", "m1.txt", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert [(f["path"], f["line"]) for f in parse_output(done.stdout)] == [("<commit-msg>", "4")]


# ---- gitlinks are found from the index, whatever the diff settings say -----------------------------

GITLINK = "160000,1111111111111111111111111111111111111111,vendor/sub"


def test_a_staged_gitlink_is_found_even_if_the_diff_is_told_to_ignore_submodules(repo, keyfile):
    git(repo, "config", "diff.ignoreSubmodules", "all")
    git(repo, "update-index", "--add", "--cacheinfo", GITLINK)
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert found(done) == [("vendor/sub", "submodule")]


def test_a_staged_gitlink_is_found_even_if_gitmodules_says_ignore_all(repo, keyfile):
    write(
        repo,
        ".gitmodules",
        '[submodule "vendor/sub"]\n\tpath = vendor/sub\n\turl = https://example.invalid/x.git\n\tignore = all\n',
    )
    git(repo, "update-index", "--add", "--cacheinfo", GITLINK)
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert ("vendor/sub", "submodule") in found(done)


def test_a_gitlink_that_was_committed_earlier_is_still_refused_when_staging_other_files(repo, keyfile):
    git(repo, "update-index", "--add", "--cacheinfo", GITLINK)
    commit(repo, "a submodule")
    write(repo, "a.txt", "clean\n")
    git(repo, "add", "a.txt")
    done = run_cli(["--staged", "--key-file", keyfile], repo)
    assert done.returncode == 1
    assert ("vendor/sub", "submodule") in found(done)


# ---- --all reads the index ----------------------------------------------------------------------


def test_all_reads_tracked_files_from_the_index_and_not_from_the_worktree(repo, keyfile):
    write(repo, "tracked.txt", "clean\n")
    git(repo, "add", "tracked.txt")
    commit(repo, "base")
    write(repo, "tracked.txt", "Zorblax\n")  # changed in the worktree, not staged
    assert run_cli(["--all", "--key-file", keyfile], repo).returncode == 0

    git(repo, "add", "tracked.txt")  # now the index holds it
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 1 and found(done) == [("tracked.txt", "denylist")]

    write(repo, "tracked.txt", "clean again\n")  # the worktree is clean, the index is not
    assert run_cli(["--all", "--key-file", keyfile], repo).returncode == 1


def test_all_scans_a_tracked_file_that_is_missing_from_the_worktree_from_the_index(repo, keyfile):
    write(repo, "gone.txt", "Zorblax\n")
    git(repo, "add", "gone.txt")
    commit(repo, "base")
    (repo / "gone.txt").unlink()
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert found(done) == [("gone.txt", "denylist")]


def test_all_still_reads_untracked_files_from_the_worktree(repo, keyfile):
    write(repo, "new.txt", "Zorblax\n")
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 1 and found(done) == [("new.txt", "denylist")]


def test_all_stops_on_an_unmerged_index(repo, keyfile):
    blobs = [
        git(repo, "hash-object", "-w", "--stdin", input=text).stdout.decode().strip()
        for text in (b"base\n", b"ours\n", b"theirs\n")
    ]
    entries = "".join(f"100644 {blob} {stage}\tconflict.txt\n" for stage, blob in enumerate(blobs, 1))
    git(repo, "update-index", "--index-info", input=entries.encode())
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 2
    assert "resolve merge conflicts first" in done.stderr


# ---- walking folders and naming paths ------------------------------------------------------------


def _junction(link, target):
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True
    )
    if made.returncode != 0:
        pytest.skip("this machine cannot create junctions")


needs_windows = pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows thing")


@needs_windows
def test_a_junction_inside_a_folder_is_never_entered(repo, keyfile, tmp_path):
    outside = tmp_path / "outside"
    write(outside, "secret.txt", "Zorblax\n")
    write(repo, "docs/a.md", "clean\n")
    _junction(repo / "docs" / "linked", outside)
    done = run_cli(["docs", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 files" in done.stdout


@needs_windows
def test_a_path_that_goes_through_a_junction_out_of_the_repository_is_refused(repo, keyfile, tmp_path):
    outside = tmp_path / "outside"
    write(outside, "secret.txt", "Zorblax\n")
    (repo / "docs").mkdir()
    _junction(repo / "docs" / "linked", outside)
    done = run_cli(["docs/linked/secret.txt", "--key-file", keyfile], repo)
    assert done.returncode == 2, done.stdout + done.stderr
    assert "outside the repository" in done.stderr


def test_an_unreadable_folder_is_a_configuration_error_with_a_masked_path(repo, keyfile, monkeypatch):
    write(repo, "docs/Zorblax-locked/a.md", "clean\n")
    real_scandir = os.scandir

    def scandir(path="."):
        if os.path.basename(os.fspath(path)).endswith("locked"):
            raise PermissionError(13, "no access", os.fspath(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    code, out, err = call_main(["docs", "--key-file", keyfile], cwd=repo, env={})
    assert code == 2, out + err
    assert "cannot read file" in err and "Traceback" not in err
    assert "zorblax" not in (out + err).lower() and "[private:" in err


def test_a_path_outside_the_repository_is_refused(repo, keyfile, tmp_path):
    outside = write(tmp_path, "outside.txt", "Zorblax\n")
    for argument in (str(outside), os.path.join("..", "outside.txt")):
        done = run_cli([argument, "--key-file", keyfile], repo)
        assert done.returncode == 2, (argument, done.stdout, done.stderr)
        assert "outside the repository" in done.stderr
        assert "outside.txt" not in done.stderr


def test_a_folder_outside_the_repository_is_refused_too(repo, keyfile, tmp_path):
    write(tmp_path, "elsewhere/a.md", "Zorblax\n")
    done = run_cli([str(tmp_path / "elsewhere"), "--key-file", keyfile], repo)
    assert done.returncode == 2
    assert "outside the repository" in done.stderr


def test_a_path_inside_the_repository_written_in_a_roundabout_way_is_accepted(repo, keyfile):
    write(repo, "docs/a.md", "clean\n")
    done = run_cli([os.path.join("docs", "..", "docs", "a.md"), "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout + done.stderr


# ---- what is printed ------------------------------------------------------------------------------


def _sha8(path: str) -> str:
    import hashlib

    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:8]


def test_without_a_key_a_path_is_printed_as_a_hash_of_itself(repo):
    name = "zorblax-notes/" + "list.txt"
    write(repo, name, loot_line() + "\n")
    code, out, err = call_main([name], cwd=repo)
    assert code == 1, out + err
    assert [(f["path"], f["rule"]) for f in parse_output(out)] == [(f"<path:{_sha8(name)}>", "log-loot")]
    assert "zorblax" not in (out + err).lower()


def test_without_a_key_a_ref_name_is_hashed_but_a_commit_label_is_not(repo):
    commit_as(repo, "paste " + loot_line())
    env = dict(os.environ, GIT_COMMITTER_EMAIL="someone@example.invalid")
    git(repo, "tag", "-a", "-m", "release", "zorblax-v1", env=env)
    code, out, err = call_main(["--history", "--identity", ALLOWED], cwd=repo)
    assert code == 1, out + err
    label = "<ref:refs/tags/zorblax-v1>"
    assert sorted(f["path"] for f in parse_output(out)) == sorted(
        [f"<commit:{abbreviated(repo)}>", f"<path:{_sha8(label)}>"]
    )
    assert "zorblax" not in (out + err).lower()


def test_without_a_key_an_unreadable_file_is_named_by_hash(repo, monkeypatch):
    name = "zorblax-locked.txt"
    write(repo, name, "clean\n")
    real_open = open

    def refuse(file, *args, **kwargs):
        if os.fspath(file).endswith(name):
            raise PermissionError(13, "no access", os.fspath(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refuse)
    code, out, err = call_main([name], cwd=repo)
    assert code == 2, out + err
    assert f"<path:{_sha8(name)}>" in err and "zorblax" not in err.lower()


def test_with_explain_on_a_terminal_a_keyless_run_shows_the_real_path(repo):
    name = "zorblax-notes.txt"
    write(repo, name, loot_line() + "\n")
    code, out, err = call_main(["--explain", name], cwd=repo, env={}, tty=True)
    assert code == 1, out + err
    assert any(line.startswith(name + ":1:1: log-loot") for line in out.splitlines()), out


def test_a_keyed_run_still_prints_paths_with_the_private_part_replaced(repo, keyfile):
    write(repo, "Zorblax/list.txt", loot_line() + "\n")
    done = run_cli(["Zorblax/list.txt", "--key-file", keyfile], repo)
    assert found(done)[0][0] == f"[private:{tag('zorblax')}]/list.txt"


@pytest.mark.parametrize(
    "args,expected,forbidden",
    [
        (["--key-file"], "usage error: --key-file", ""),
        (["--identity"], "usage error: --identity", ""),
        (["--history=zorblax"], "usage error: --history", "zorblax"),
        (["--bogus-zorblax"], "usage error", "zorblax"),
        (["zorblax.txt", "--all"], "usage error", "zorblax"),
    ],
    ids=["missing value", "missing address", "value given to a flag", "unknown option", "path and mode"],
)
def test_usage_errors_never_echo_what_was_typed(repo, args, expected, forbidden):
    code, out, err = call_main(args, cwd=repo)
    assert code == 2, out + err
    assert err.strip().startswith(expected), err
    assert "Traceback" not in err and (not forbidden or forbidden not in (out + err).lower())


def test_an_unknown_option_prints_no_option_name(repo):
    code, out, err = call_main(["--no-such-flag"], cwd=repo)
    assert code == 2 and err.strip() == "usage error"


# ---- the lists of digests are read strictly -----------------------------------------------------


def _write_lists(repo, deny_lines=None, allow_lines=None, deny_bytes=None):
    deny_text = "\n".join(deny_lines) + "\n" if deny_lines is not None else None
    if deny_bytes is not None:
        write(repo, "privacy/denylist.hmac", deny_bytes)
    elif deny_text is not None:
        write(repo, "privacy/denylist.hmac", deny_text)
    if allow_lines is not None:
        write(repo, "privacy/allow.hmac", "\n".join(allow_lines) + "\n")


GOOD = h("zorblax")
BAD_DIGESTS = {
    "a word": "zorblax",
    "uppercase": GOOD.upper(),
    "63 digits": GOOD[:-1],
    "65 digits": GOOD + "0",
    "two on a line": GOOD + " " + GOOD,
    "a prefix": "0x" + GOOD[2:],
    "a trailing word": GOOD + " zorblax",
}


@pytest.mark.parametrize("bad", list(BAD_DIGESTS.values()), ids=list(BAD_DIGESTS))
def test_a_denylist_line_that_is_not_exactly_64_lowercase_hex_digits_is_a_configuration_error(
    repo, keyfile, bad
):
    _write_lists(repo, deny_lines=[HEADER_DENY, "# key-check: " + key_check(), GOOD, "", bad])
    write(repo, "ok.txt", "nothing\n")
    code, out, err = call_main(["ok.txt", "--key-file", keyfile], cwd=repo)
    assert code == 2, out + err
    assert err.strip() == "denylist malformed (line 5)"


@pytest.mark.parametrize("bad", list(BAD_DIGESTS.values()), ids=list(BAD_DIGESTS))
def test_an_allow_list_line_that_is_not_exactly_64_lowercase_hex_digits_is_a_configuration_error(
    repo, keyfile, bad
):
    _write_lists(repo, allow_lines=[HEADER_ALLOW, GOOD, bad])
    write(repo, "ok.txt", "nothing\n")
    code, out, err = call_main(["ok.txt", "--key-file", keyfile], cwd=repo)
    assert code == 2, out + err
    assert err.strip() == "allow list malformed (line 3)"


def test_the_lists_may_have_a_bom_crlf_blank_lines_comments_and_padding(repo, keyfile):
    body = "\r\n".join(
        [HEADER_DENY, "# key-check: " + key_check(), "", "  " + h("zorblax") + "  ", "# a note", h("quimmet"), ""]
    )
    _write_lists(repo, deny_bytes=b"\xef\xbb\xbf" + body.encode())
    write(repo, "ok.txt", "Zorblax\n")
    done = run_cli(["ok.txt", "--key-file", keyfile], repo)
    assert done.returncode == 1 and [f["rule"] for f in parse_output(done.stdout)] == ["denylist"]


def test_a_malformed_list_is_an_error_even_when_the_key_is_not_required(repo, keyfile):
    _write_lists(repo, deny_lines=[HEADER_DENY, "not a digest"])
    write(repo, "ok.txt", "nothing\n")
    code, out, err = call_main(["ok.txt", "--key-file", keyfile], cwd=repo)
    assert code == 2 and "denylist malformed (line 2)" in err


def test_a_push_check_without_a_remote_name_is_a_configuration_error(repo, keyfile):
    code, out, err = call_main(["--pre-push", "", "--key-file", keyfile], cwd=repo, stdin="")
    assert code == 2 and err.strip() == "usage error: --pre-push needs the name of a remote"


@needs_windows
def test_all_does_not_read_untracked_files_behind_a_junction_that_leaves_the_repository(
    repo, keyfile, tmp_path
):
    outside = tmp_path / "outside"
    write(outside, "secret.txt", "Zorblax\n")
    write(repo, "a.txt", "clean\n")
    _junction(repo / "linked", outside)
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "skipped 1 non-regular" in done.stdout


@needs_windows
def test_all_still_reads_untracked_files_behind_a_junction_that_stays_inside_the_repository(
    repo, keyfile
):
    write(repo, "real/secret.txt", "Zorblax\n")
    _junction(repo / "linked", repo / "real")
    done = run_cli(["--all", "--key-file", keyfile], repo)
    assert done.returncode == 1, done.stdout + done.stderr
    assert ("real/secret.txt", "denylist") in found(done)
