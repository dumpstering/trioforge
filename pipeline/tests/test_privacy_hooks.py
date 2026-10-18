"""Tests for the git hooks and the install script (addendum cases A17 and A18, and more).

The hooks are POSIX sh. Git for Windows ships one; the tests that run a hook need ``sh``.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from test_privacy_helpers import (  # noqa: F401  (fixtures are used by name)
    KEY_HEX,
    ROOT,
    commit,
    find_sh,
    git,
    gitenv,
    make_repo,
    privacy_files,
    write,
)

HOOK_NAMES = ["pre-commit", "commit-msg", "pre-push"]
HOOK_DIR = ROOT / "scripts" / "hooks"
INSTALL_SCRIPT = ROOT / "scripts" / "install-hooks.sh"
SH = find_sh()
NO_VENV_MESSAGE = "privacy hook: no .venv python found; run the setup in README"

needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX sh on this machine")


def _sh(script, *args, cwd, env=None):
    return subprocess.run(
        [SH, Path(script).as_posix(), *(Path(a).as_posix() if isinstance(a, Path) else str(a) for a in args)],
        cwd=cwd,
        env=env if env is not None else dict(os.environ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# ---- the files themselves -------------------------------------------------------------


@pytest.mark.parametrize("name", HOOK_NAMES + ["../install-hooks.sh"])
def test_the_scripts_exist_start_with_a_shebang_and_use_lf_line_endings(name):
    data = (HOOK_DIR / name).read_bytes()
    assert data.startswith(b"#!/bin/sh\n")
    assert b"\r" not in data


def test_a18_every_hook_is_committed_with_mode_100755():
    inside = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, capture_output=True, text=True
    )
    if inside.returncode != 0:
        pytest.skip("not a git checkout")
    listing = subprocess.run(
        ["git", "ls-files", "-s", "scripts/hooks/"], cwd=ROOT, capture_output=True, text=True
    )
    entries = [line.split() for line in listing.stdout.splitlines() if line.strip()]
    assert sorted(parts[3] for parts in entries) == sorted(f"scripts/hooks/{n}" for n in HOOK_NAMES)
    assert {parts[0] for parts in entries} == {"100755"}


# ---- A17: no interpreter ----------------------------------------------------------------


@needs_sh
@pytest.mark.parametrize("name", HOOK_NAMES)
def test_a17_a_hook_without_a_venv_exits_2_with_the_message_never_127(name, tmp_path, gitenv):
    repo = make_repo(tmp_path / "bare-checkout")
    (repo / "scripts" / "hooks").mkdir(parents=True)
    shutil.copy(HOOK_DIR / name, repo / "scripts" / "hooks" / name)
    args = {
        "pre-commit": [],
        "commit-msg": [write(repo, ".git/COMMIT_EDITMSG", "message\n")],
        "pre-push": ["origin", "file:///nowhere"],
    }[name]
    done = _sh(repo / "scripts" / "hooks" / name, *args, cwd=repo)
    assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
    assert NO_VENV_MESSAGE in done.stderr


# ---- the install script ----------------------------------------------------------------


@needs_sh
def test_install_script_points_core_hooks_path_at_scripts_hooks(tmp_path, gitenv):
    repo = make_repo(tmp_path / "clone")
    (repo / "scripts" / "hooks").mkdir(parents=True)
    shutil.copy(INSTALL_SCRIPT, repo / "scripts" / "install-hooks.sh")
    for name in HOOK_NAMES:
        shutil.copy(HOOK_DIR / name, repo / "scripts" / "hooks" / name)
    done = _sh(repo / "scripts" / "install-hooks.sh", cwd=repo)
    assert done.returncode == 0, done.stdout + done.stderr
    configured = git(repo, "config", "--get", "core.hooksPath").stdout.decode().strip()
    assert configured == "scripts/hooks"


@needs_sh
@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no executable bit to check")
def test_install_script_makes_the_hooks_executable(tmp_path, gitenv):
    repo = make_repo(tmp_path / "clone")
    (repo / "scripts" / "hooks").mkdir(parents=True)
    shutil.copy(INSTALL_SCRIPT, repo / "scripts" / "install-hooks.sh")
    for name in HOOK_NAMES:
        target = repo / "scripts" / "hooks" / name
        shutil.copy(HOOK_DIR / name, target)
        target.chmod(0o644)
    assert _sh(repo / "scripts" / "install-hooks.sh", cwd=repo).returncode == 0
    for name in HOOK_NAMES:
        assert os.stat(repo / "scripts" / "hooks" / name).st_mode & stat.S_IXUSR


# ---- the hooks at work, end to end, in a scratch repository ---------------------------


ALLOWED = "maintainers@trioforge.invalid"


def _hooked_repo(tmp_path, author=None):
    """A repository with the real hooks installed, the scanner package copied in, and a
    ``.venv/bin/python`` that runs the interpreter running the tests. Its committed
    ``privacy/identity.txt`` names the allowed address; ``author`` (an address) is the one the
    baseline commit is made under (the repository's default test address when None)."""
    repo = make_repo(tmp_path / "hooked")
    if author:
        git(repo, "config", "user.email", author)
    (repo / "scripts").mkdir()
    shutil.copytree(HOOK_DIR, repo / "scripts" / "hooks")
    shutil.copy(INSTALL_SCRIPT, repo / "scripts" / "install-hooks.sh")
    shutil.copytree(
        ROOT / "pipeline" / "trioforge",
        repo / "pipeline" / "trioforge",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    fake_python = repo / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_bytes(
        f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n'.encode()
    )
    fake_python.chmod(0o755)  # git runs the hooks, and the hooks run this, directly on Linux
    privacy_files(repo, identity=ALLOWED)
    write(repo, ".gitignore", ".venv/\npipeline/\n__pycache__/\n")
    write(repo, "README.md", "hello\n")
    git(repo, "add", ".gitignore", "README.md", "scripts", "privacy")
    commit(repo, "baseline")  # before the hooks are installed
    assert _sh(repo / "scripts" / "install-hooks.sh", cwd=repo).returncode == 0
    return repo


def _hook_env():
    env = dict(os.environ)
    env["TRIOFORGE_PRIVACY_KEY"] = KEY_HEX
    env["PYTHONUTF8"] = "1"
    return env


@needs_sh
def test_pre_commit_blocks_a_staged_name_and_allows_clean_files(tmp_path, gitenv):
    repo = _hooked_repo(tmp_path)
    env = _hook_env()

    write(repo, "notes.txt", "all clean\n")
    git(repo, "add", "notes.txt", env=env)
    done = git(repo, "commit", "-m", "clean change", env=env, check=False)
    assert done.returncode == 0, done.stdout + done.stderr

    write(repo, "notes.txt", "Zorblax was here\n")
    git(repo, "add", "notes.txt", env=env)
    done = git(repo, "commit", "-m", "leaky change", env=env, check=False)
    assert done.returncode != 0
    blocked = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert "denylist" in blocked
    assert "zorblax" not in blocked.lower()
    log = git(repo, "log", "--format=%s").stdout.decode().split("\n")
    assert "leaky change" not in log


@needs_sh
def test_commit_msg_blocks_a_name_in_the_message(tmp_path, gitenv):
    repo = _hooked_repo(tmp_path)
    env = _hook_env()
    write(repo, "notes.txt", "all clean\n")
    git(repo, "add", "notes.txt", env=env)
    done = git(repo, "commit", "-m", "thanks Quimmet", env=env, check=False)
    assert done.returncode != 0
    blocked = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert "<commit-msg>" in blocked
    assert "quimmet" not in blocked.lower()


@needs_sh
def test_hooks_refuse_to_run_without_a_key(tmp_path, gitenv):
    repo = _hooked_repo(tmp_path)
    env = _hook_env()
    env["TRIOFORGE_PRIVACY_KEY"] = ""  # present but empty: an invalid key, never "skip"
    write(repo, "notes.txt", "all clean\n")
    git(repo, "add", "notes.txt", env=env)
    done = git(repo, "commit", "-m", "clean change", env=env, check=False)
    assert done.returncode != 0
    assert b"privacy key invalid" in done.stdout + done.stderr


@needs_sh
def test_pre_push_scans_history_and_identity_before_anything_leaves(tmp_path, gitenv):
    repo = _hooked_repo(tmp_path)
    env = _hook_env()
    git(repo, "config", "user.email", ALLOWED)
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", remote)
    git(repo, "remote", "add", "origin", remote.as_posix())

    # The baseline commit used another address than the one in privacy/identity.txt, so the
    # identity check stops the push.
    done = git(repo, "push", "origin", "main", env=env, check=False)
    assert done.returncode != 0
    assert b"identity" in done.stdout + done.stderr
    assert b"test@example.invalid" not in done.stdout + done.stderr

    # Re-author the baseline (a test repo, so rewriting is fine) and the push goes through.
    git(repo, "commit", "-q", "--amend", "--reset-author", "--no-edit", "--no-verify", env=env)
    done = git(repo, "push", "origin", "main", env=env, check=False)
    assert done.returncode == 0, done.stdout + done.stderr

    # A name that was committed and then deleted still blocks the next push.
    write(repo, "old.txt", "Zorblax\n")
    git(repo, "add", "old.txt", env=env)
    git(repo, "commit", "-q", "-m", "oops", "--no-verify", env=env)
    git(repo, "rm", "-q", "old.txt", env=env)
    git(repo, "commit", "-q", "-m", "undo", "--no-verify", env=env)
    done = git(repo, "push", "origin", "main", env=env, check=False)
    assert done.returncode != 0
    blocked = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert "old.txt" in blocked and "zorblax" not in blocked.lower()


# ---- the pre-push hook checks what is sent, and who made it -----------------------------------


def _with_remote(tmp_path, repo):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", remote)
    git(repo, "remote", "add", "origin", remote.as_posix())
    return remote


def test_the_pre_push_hook_takes_the_address_from_the_committed_file_not_from_git_config():
    lines = (HOOK_DIR / "pre-push").read_text(encoding="utf-8").splitlines()
    commands = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    assert "privacy/identity.txt" in commands
    assert "git config" not in commands and "user.email" not in commands
    assert "--pre-push" in commands and "--require-key" in commands


@needs_sh
def test_pre_push_ignores_git_config_and_trusts_the_committed_address(tmp_path, gitenv):
    repo = _hooked_repo(tmp_path, author="someone@example.invalid")
    env = _hook_env()
    _with_remote(tmp_path, repo)
    # git config and every commit agree on one address, but the committed file names another.
    done = git(repo, "push", "origin", "main", env=env, check=False)
    assert done.returncode != 0
    output = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert "identity" in output and "someone@example.invalid" not in output
    # Once the committed file names that address, the same history may go.
    write(repo, "privacy/identity.txt", "someone@example.invalid\n")
    git(repo, "add", "privacy/identity.txt", env=env)
    git(repo, "commit", "-q", "-m", "name the address", env=env)
    done = git(repo, "push", "origin", "main", env=env, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


@needs_sh
def test_pre_push_blocks_a_remote_tag_named_with_a_private_token(tmp_path, gitenv):
    repo = _hooked_repo(tmp_path, author=ALLOWED)
    env = _hook_env()
    _with_remote(tmp_path, repo)
    done = git(repo, "push", "origin", "main:refs/tags/zorblax-v1", env=env, check=False)
    assert done.returncode != 0
    output = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert "[private:" in output and "zorblax" not in output.lower()
    done = git(repo, "push", "origin", "main:refs/tags/v1", env=env, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


@needs_sh
def test_pre_push_blocks_a_commit_that_only_the_reflog_remembers(tmp_path, gitenv):
    repo = _hooked_repo(tmp_path, author=ALLOWED)
    env = _hook_env()
    _with_remote(tmp_path, repo)
    write(repo, "leak.txt", "Zorblax\n")
    git(repo, "add", "leak.txt", env=env)
    git(repo, "commit", "-q", "-m", "oops", "--no-verify", env=env)
    lost = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    git(repo, "reset", "-q", "--hard", "HEAD~1", env=env)  # no branch or tag reaches it now
    done = git(repo, "push", "origin", "main", env=env, check=False)
    assert done.returncode == 0, done.stdout + done.stderr  # what the branches reach is clean
    done = git(repo, "push", "origin", f"{lost}:refs/heads/elsewhere", env=env, check=False)
    assert done.returncode != 0
    output = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert "leak.txt" in output and "zorblax" not in output.lower()


@needs_sh
def test_pre_push_blocks_a_commit_dated_outside_utc(tmp_path, gitenv):
    repo = _hooked_repo(tmp_path, author=ALLOWED)
    env = _hook_env()
    _with_remote(tmp_path, repo)
    local_time = dict(env, GIT_COMMITTER_DATE="2026-10-13T12:00:00-0500")
    git(repo, "commit", "-q", "--allow-empty", "-m", "late", env=local_time)
    done = git(repo, "push", "origin", "main", env=env, check=False)
    assert done.returncode != 0
    output = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert "timezone" in output and "0500" not in output
