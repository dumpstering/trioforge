"""Tests for the guard that keeps a build with seen flags out of every git work tree.

A build that merges the maintainer's private seen flags may write only outside every git work tree, or into
the git-ignored ``build/`` folder of one. "A git work tree" is any folder with a ``.git`` entry above the output:
this checkout, a sibling worktree under any name, a second clone, a folder reached through a link or through
another spelling of its path (the extended ``\\\\?\\`` prefix, an administrative share of this computer, an
8.3 short name, a trailing dot).

Every test works in throw-away repositories under a scratch folder; the real checkout is never written. The
spellings that only Windows knows are skipped elsewhere, and the ones that need an administrative share or a
short name are skipped on a computer that has none.
"""

from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_privacy_helpers import GIT_VARS, commit, git, gitenv, make_repo, write  # noqa: F401  (gitenv is a fixture)
from trioforge.data import catalog
from trioforge.data.catalog import OUTPUT_FILES, BuildError, build_catalog, check_seen_output, main

WINDOWS = sys.platform == "win32"
REAL_REPO = Path(__file__).resolve().parents[2]


def build_trees(base):
    """A real repository that ignores ``build/``, a linked worktree whose name does not look like one, and a
    second clone elsewhere. Call it with git isolated from the machine's configuration."""
    repo = make_repo(base / "checkouts" / "trioforge")
    write(repo, ".gitignore", "build/\n")
    write(repo, "derived/placeholder.txt", "x\n")
    git(repo, "add", ".gitignore", "derived/placeholder.txt")
    commit(repo, "start")
    worktree = base / "checkouts" / "tf-feature"
    git(repo, "worktree", "add", "-q", "-b", "feature", str(worktree))
    clone = base / "elsewhere" / "trioforge-copy"
    git(base, "clone", "-q", str(repo), str(clone))
    return SimpleNamespace(repo=repo, worktree=worktree, clone=clone, tmp=base)


@pytest.fixture(scope="module")
def trees(tmp_path_factory):
    """The three trees, made once for the tests that only look at them."""
    base = tmp_path_factory.mktemp("trees")
    config = base / "empty.gitconfig"
    config.write_bytes(b"")
    with pytest.MonkeyPatch.context() as isolated:
        isolated.setenv("GIT_CONFIG_GLOBAL", str(config))
        isolated.setenv("GIT_CONFIG_NOSYSTEM", "1")
        isolated.setenv("GIT_TERMINAL_PROMPT", "0")
        isolated.setenv("TZ", "UTC")
        for name in GIT_VARS:
            isolated.delenv(name, raising=False)
        return build_trees(base)


@pytest.fixture
def checkouts(trees, gitenv, monkeypatch):
    """The shared trees, with the first one as the catalog's checkout. Do not change them."""
    monkeypatch.setattr(catalog, "REPO_ROOT", trees.repo)
    return trees


@pytest.fixture
def fresh(tmp_path, gitenv, monkeypatch):
    """Trees of this test's own, for a test that changes them."""
    made = build_trees(tmp_path / "fresh")
    monkeypatch.setattr(catalog, "REPO_ROOT", made.repo)
    return made


def refused(path):
    with pytest.raises(BuildError, match="refused"):
        check_seen_output(path)


def make_link(link, target):
    """A folder link: a symlink, else a junction. Skips the test where neither can be made."""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return
    except (OSError, NotImplementedError, AttributeError):
        pass
    if WINDOWS and subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True).returncode == 0:
        return
    pytest.skip("this system does not let the test make a folder link")


# ---- inside a work tree, only build/ and only when git ignores it ----------------------------------------------


@pytest.mark.parametrize(
    "where",
    [
        "derived",
        "derived/sub",
        ".",
        "docs",
        "sources/eqlwiki",
        "build/../derived",
        "buildx",
        "build/../buildx/y",
        "derived/../derived/x",
        "newdir/deeper",
        ".git/hooks",
    ],
)
def test_a_folder_of_the_repository_other_than_build_is_refused(checkouts, where):
    refused(checkouts.repo / where)


@pytest.mark.parametrize("where", ["build", "build/catalog-with-seen", "build/a/b/c", "build/../build/x"])
def test_build_is_allowed_when_git_says_it_ignores_it(checkouts, where):
    before = sorted(os.listdir(checkouts.repo))
    check_seen_output(checkouts.repo / where)  # the folder need not exist yet
    assert sorted(os.listdir(checkouts.repo)) == before  # and the check creates nothing


def test_a_relative_folder_is_read_from_the_current_folder(checkouts, monkeypatch):
    monkeypatch.chdir(checkouts.repo)
    refused("derived")
    refused(".")
    refused(os.path.join("build", "..", "derived"))
    check_seen_output(os.path.join("build", "catalog-with-seen"))
    monkeypatch.chdir(checkouts.repo / "derived")
    refused(".")
    refused(os.path.join("..", "docs"))
    check_seen_output(os.path.join("..", "build", "x"))


def test_a_folder_below_a_file_is_still_a_folder_of_the_repository(checkouts):
    refused(checkouts.repo / "derived" / "placeholder.txt" / "out")


def test_build_is_refused_when_git_does_not_ignore_it(fresh):
    write(fresh.repo, ".gitignore", "something-else/\n")
    refused(fresh.repo / "build" / "catalog-with-seen")


def test_build_is_refused_when_git_ignores_only_some_of_the_files_written_there(fresh):
    write(fresh.repo, ".gitignore", "build/catalog.json\n")
    refused(fresh.repo / "build")
    assert "catalog.json" in OUTPUT_FILES and len(OUTPUT_FILES) > 1


def test_build_is_refused_when_one_of_its_files_is_already_tracked(fresh):
    write(fresh.repo, "build/catalog-with-seen/catalog.json", "{}\n")
    git(fresh.repo, "add", "-f", "build/catalog-with-seen/catalog.json")
    refused(fresh.repo / "build" / "catalog-with-seen")
    check_seen_output(fresh.repo / "build" / "other")  # another folder of build/ is still fine


def test_build_is_refused_when_git_cannot_answer(checkouts, monkeypatch):
    monkeypatch.setattr(catalog.shutil, "which", lambda name, *args, **kwargs: None)
    refused(checkouts.repo / "build")
    refused(checkouts.repo / "derived")


def test_build_is_refused_when_the_git_entry_is_not_a_repository(tmp_path, monkeypatch, gitenv):
    fake = tmp_path / "not-quite"
    (fake / ".git").mkdir(parents=True)  # a folder named .git that holds nothing
    monkeypatch.setattr(catalog, "REPO_ROOT", tmp_path / "somewhere-else")
    refused(fake / "build" / "x")
    refused(fake / "derived")


def test_the_answer_comes_from_the_repository_of_the_output_not_from_the_environment(checkouts, tmp_path, monkeypatch):
    other = make_repo(tmp_path / "other")  # a repository that ignores nothing
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    check_seen_output(checkouts.repo / "build" / "x")
    refused(checkouts.repo / "derived")


def test_a_repository_inside_build_is_a_work_tree_of_its_own(fresh):
    inner = make_repo(fresh.repo / "build" / "inner")  # a clone kept in the ignored build/ of another
    refused(inner / "derived")  # inside the inner tree and not under its build/
    refused(inner / "newdir")
    write(inner, ".gitignore", "build/\n")
    check_seen_output(inner / "build" / "x")  # the inner tree ignores its build/ and so does the outer one
    write(inner, ".gitignore", "something-else/\n")
    refused(inner / "build" / "x")  # the inner tree stopped ignoring it


# ---- every other work tree: a sibling worktree under any name, a second clone ------------------------------------


def test_a_sibling_worktree_that_is_not_named_like_one_is_refused(checkouts):
    assert (checkouts.worktree / ".git").is_file()  # a linked worktree has a .git file, not a folder
    refused(checkouts.worktree / "derived")
    refused(checkouts.worktree / "derived" / "deeper")
    refused(checkouts.worktree)
    check_seen_output(checkouts.worktree / "build" / "catalog-with-seen")  # its own build/ is ignored too


def test_a_second_clone_is_refused(checkouts):
    assert (checkouts.clone / ".git").is_dir()
    refused(checkouts.clone / "derived")
    refused(checkouts.clone)
    refused(checkouts.clone / "docs" / "new")
    check_seen_output(checkouts.clone / "build")


def test_outside_every_work_tree_is_allowed(checkouts):
    check_seen_output(checkouts.tmp / "private-preview")
    check_seen_output(checkouts.tmp / "elsewhere" / "a" / "b")
    check_seen_output(checkouts.tmp / "checkouts" / "not-a-repository" / "derived")


def test_a_repository_without_a_git_entry_is_still_this_checkout(tmp_path, monkeypatch):
    """A checkout that is only a copy of the files (no .git) has no ignore rules to ask: build/ is the only way in."""
    root = tmp_path / "unpacked"
    for name in ("derived", "build"):
        (root / name).mkdir(parents=True)
    monkeypatch.setattr(catalog, "REPO_ROOT", root)
    refused(root / "derived")
    refused(root)
    check_seen_output(root / "build" / "catalog-with-seen")
    check_seen_output(tmp_path / "elsewhere")


# ---- links -----------------------------------------------------------------------------------------------------------


def test_a_link_from_outside_into_the_repository_is_refused(checkouts, tmp_path):
    link = tmp_path / "link-into-the-repository"
    make_link(link, checkouts.repo)
    refused(link / "derived")
    refused(link / "derived" / "deeper")
    refused(link)
    check_seen_output(link / "build" / "x")  # it is the repository's own build/ whatever the way in


def test_a_link_to_the_derived_folder_is_refused(checkouts, tmp_path):
    link = tmp_path / "link-to-derived"
    make_link(link, checkouts.repo / "derived")
    refused(link)
    refused(link / "out")


def test_a_link_from_outside_into_a_sibling_worktree_or_a_clone_is_refused(checkouts, tmp_path):
    for index, target in enumerate((checkouts.worktree, checkouts.clone)):
        link = tmp_path / f"link-{index}"
        make_link(link, target)
        refused(link / "derived")
        refused(link)


def test_a_link_inside_build_that_leaves_the_repository_is_allowed(fresh, tmp_path):
    target = tmp_path / "private-preview-target"
    target.mkdir()
    (fresh.repo / "build").mkdir()
    link = fresh.repo / "build" / "elsewhere"
    make_link(link, target)
    check_seen_output(link / "out")  # the flags land outside every work tree


# ---- other spellings of the same folder (Windows) ---------------------------------------------------------------------


def spelled(how, path):
    """Another way to write ``path`` on Windows, or None where this computer has no such way."""
    text = str(path)
    drive, rest = os.path.splitdrive(text)
    share = drive[:1] + "$" + rest
    host = {"localhost": "localhost", "loopback address": "127.0.0.1", "computer name": socket.gethostname()}
    if how == "extended prefix":
        return "\\\\?\\" + text
    if how == "device prefix":
        return "\\\\.\\" + text
    if how in host:
        return "\\\\" + host[how] + "\\" + share
    if how == "extended UNC prefix":
        return "\\\\?\\UNC\\localhost\\" + share
    if how == "short name":
        buffer = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetShortPathNameW(text, buffer, 1024)
        return buffer.value if buffer.value and buffer.value.lower() != text.lower() else None
    if how == "upper case":
        return text.upper()
    if how == "forward slashes":
        return text.replace("\\", "/")
    if how == "trailing dot":
        return text + "."
    if how == "trailing space":
        return text + " "
    raise AssertionError(how)


SPELLINGS = [
    "extended prefix",
    "device prefix",
    "localhost",
    "loopback address",
    "computer name",
    "extended UNC prefix",
    "short name",
    "upper case",
    "forward slashes",
    "trailing dot",
    "trailing space",
]


def other_spelling(how, existing_folder):
    if not WINDOWS:
        pytest.skip("these are Windows spellings")
    found = spelled(how, existing_folder)
    if found is None:
        pytest.skip("this computer has no such spelling")
    if how in ("localhost", "loopback address", "computer name", "extended UNC prefix") and not os.path.isdir(found):
        pytest.skip("this computer does not share its drives to itself")
    return found


@pytest.mark.parametrize("how", SPELLINGS)
def test_every_spelling_of_a_folder_of_the_repository_is_refused(checkouts, how):
    refused(other_spelling(how, checkouts.repo / "derived"))
    refused(other_spelling(how, checkouts.repo) + "\\derived\\new\\deeper")
    refused(other_spelling(how, checkouts.repo))


@pytest.mark.parametrize("how", SPELLINGS)
def test_every_spelling_of_a_sibling_worktree_or_a_second_clone_is_refused(checkouts, how):
    for tree in (checkouts.worktree, checkouts.clone):
        refused(other_spelling(how, tree / "derived"))
        refused(other_spelling(how, tree) + "\\docs\\new")


@pytest.mark.parametrize("how", SPELLINGS)
def test_every_spelling_of_the_checkout_is_refused_even_without_a_git_entry(tmp_path, monkeypatch, how):
    root = tmp_path / "unpacked"
    (root / "derived").mkdir(parents=True)
    monkeypatch.setattr(catalog, "REPO_ROOT", root)
    refused(other_spelling(how, root / "derived"))
    refused(other_spelling(how, root))


@pytest.mark.skipif(not WINDOWS, reason="a spelling that only Windows knows")
def test_a_spelling_that_names_the_volume_by_its_guid_is_refused(checkouts):
    drive, rest = os.path.splitdrive(str(checkouts.repo))
    buffer = ctypes.create_unicode_buffer(260)
    if not ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(drive + "\\", buffer, 260):
        pytest.skip("this volume has no GUID path")
    folder = buffer.value.rstrip("\\") + rest + "\\derived"  # \\?\Volume{...}\...
    if not os.path.isdir(folder):
        pytest.skip("this computer does not open its volume by GUID")
    refused(folder)


# ---- through the whole build and the command line --------------------------------------------------------------------


def seen_build_refused_before_anything_is_read(tmp_path, out):
    """Nothing the build reads exists, so a refusal that names the folder proves it came first."""
    before = sorted(str(p) for p in Path(out).rglob("*")) if Path(out).is_dir() else None
    with pytest.raises(BuildError, match="refused"):
        build_catalog(tmp_path / "no-such-wiki", tmp_path / "no-such-client", out, seen_path=tmp_path / "no-such-seen.json", workers=0)
    assert (sorted(str(p) for p in Path(out).rglob("*")) if Path(out).is_dir() else None) == before  # nothing written either


def test_a_seen_build_into_a_sibling_worktree_a_clone_or_a_link_is_refused_before_anything_is_read(checkouts, tmp_path):
    link = tmp_path / "link-into-the-repository"
    make_link(link, checkouts.repo)
    for out in (checkouts.worktree / "derived", checkouts.clone / "derived", link / "derived", checkouts.repo / "derived"):
        seen_build_refused_before_anything_is_read(tmp_path, out)


@pytest.mark.parametrize("how", ["extended prefix", "localhost", "extended UNC prefix"])
def test_a_seen_build_into_another_spelling_of_derived_is_refused_before_anything_is_read(checkouts, tmp_path, how):
    seen_build_refused_before_anything_is_read(tmp_path, other_spelling(how, checkouts.repo / "derived"))


def test_the_command_line_refuses_a_sibling_worktree_with_one_line_and_status_two(checkouts, tmp_path, capsys):
    seen = tmp_path / "flags-copy.json"
    seen.write_text('{"keys": []}', encoding="utf-8")
    argv = ["--wiki", str(tmp_path / "w"), "--client", str(tmp_path / "c"), "--seen", str(seen), "--out", str(checkouts.worktree / "derived")]
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "refused" in err and err.count("\n") == 1
    assert str(tmp_path) not in err and str(checkouts.tmp) not in err  # the message names no folder of this machine


# ---- the real checkout -----------------------------------------------------------------------------------------------


def test_the_default_output_of_a_seen_build_is_allowed_in_this_checkout_and_derived_is_not(gitenv, monkeypatch):
    """This repository's own .gitignore must keep ignoring build/, or the default output of a seen build would stop working."""
    monkeypatch.setattr(catalog, "REPO_ROOT", REAL_REPO)
    check_seen_output(REAL_REPO / "build" / "catalog-with-seen")
    refused(REAL_REPO / "derived")
    refused(REAL_REPO / "rules")
