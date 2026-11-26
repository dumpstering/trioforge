"""Tests for ``trioforge.checks_dir``: the one folder, outside every worktree, that the scheduled checks leave their stamps, logs and reports in and that the
release build reads the stamps from.

The checks run in one checkout (the main one, from the Task Scheduler), and a release build runs from a worktree of its own, so a stamp in the ``build/`` of the
first would never be seen by the second. The folder is ``$TRIOFORGE_CHECKS_DIR`` if that is set (an empty value counts as unset), else
``~/.local/state/trioforge/checks`` -- on Windows too: %LOCALAPPDATA% of a program that runs from the Claude app is a private copy that the Task Scheduler never sees.
Python (here) and the smoke check (Node, ``scripts/smoke_live.mjs``) work it out by the same rules, and a test holds them to give the same answers.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from checks_helpers import REPO
from test_site_build import need_node

from trioforge import checks_dir as module
from trioforge.checks_dir import ENVIRONMENT_VARIABLE, checks_dir, is_absolute

HOME = Path("home") / "someone"  # an invented home folder (the function does not need it to exist)
LOCAL = "AppData-Local"  # an invented value of %LOCALAPPDATA%
PLATFORMS = ["win32", "linux", "darwin"]
ABSOLUTE = {"win32": "C:\\stamps", "linux": "/stamps", "darwin": "/stamps"}  # an absolute path of each kind of platform
DEFAULT = HOME / ".local" / "state" / "trioforge" / "checks"


def test_the_variable_is_called_TRIOFORGE_CHECKS_DIR():
    assert ENVIRONMENT_VARIABLE == "TRIOFORGE_CHECKS_DIR"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_the_variable_names_the_folder_on_any_platform(platform):
    given = ABSOLUTE[platform]
    assert checks_dir({ENVIRONMENT_VARIABLE: given, "LOCALAPPDATA": LOCAL}, platform=platform, home=HOME) == Path(given)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_white_space_round_the_name_is_no_part_of_it(platform):
    assert checks_dir({ENVIRONMENT_VARIABLE: f"  {ABSOLUTE[platform]}\n"}, platform=platform, home=HOME) == Path(ABSOLUTE[platform])


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("value", ["checks", "./checks", "../checks", "build/checks", "~/checks"])
def test_a_folder_that_is_not_given_whole_is_refused_because_two_working_folders_would_mean_two_folders(platform, value):
    with pytest.raises(ValueError, match="TRIOFORGE_CHECKS_DIR"):
        checks_dir({ENVIRONMENT_VARIABLE: value}, platform=platform, home=HOME)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_the_default_is_under_the_state_folder_of_the_home_on_every_platform_windows_included(platform):
    assert checks_dir({}, platform=platform, home=HOME) == DEFAULT
    assert checks_dir({"LOCALAPPDATA": LOCAL}, platform=platform, home=HOME) == DEFAULT  # (never %LOCALAPPDATA%: on this kind of computer it is a private copy for the Claude app)


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("value", ["", "  ", "\n", "\t "])
def test_an_empty_or_blank_variable_counts_as_unset(platform, value):
    assert checks_dir({ENVIRONMENT_VARIABLE: value}, platform=platform, home=HOME) == DEFAULT


def test_it_reads_the_environment_and_the_platform_of_the_process_when_it_is_given_none(monkeypatch, tmp_path):
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, str(tmp_path / "stamps"))
    assert checks_dir() == tmp_path / "stamps"
    monkeypatch.delenv(ENVIRONMENT_VARIABLE)
    default = checks_dir()
    assert default.is_absolute() and default.parts[-4:] == (".local", "state", "trioforge", "checks")


def test_the_default_folder_is_outside_every_worktree_of_the_repository_and_outside_the_local_app_data(monkeypatch):
    monkeypatch.delenv(ENVIRONMENT_VARIABLE)
    monkeypatch.setenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    default = checks_dir().resolve()
    assert REPO.resolve() not in default.parents and default != REPO.resolve() / "build" / "checks"
    assert (Path.home() / "AppData").resolve() not in default.parents


def test_every_test_has_a_folder_of_its_own_and_never_the_real_one(monkeypatch):
    seen = Path(os.environ[ENVIRONMENT_VARIABLE])
    monkeypatch.delenv(ENVIRONMENT_VARIABLE)
    assert seen != checks_dir() and seen.is_absolute()


def test_the_module_says_what_it_is_for():
    assert "outside every worktree" in (module.__doc__ or "")


# ---- one rule for "absolute", in Python and in Node: a drive or a UNC path on Windows, a path that starts with / elsewhere ---------------------------------------

# (value, is it absolute on Windows, is it absolute elsewhere)
ABSOLUTENESS = [
    ("/TrioForge/checks", False, True),  # (rooted, but without a drive: Node called it absolute on Windows and Python did not)
    ("/", False, True),
    ("C:\\TrioForge\\checks", True, False),
    ("C:/TrioForge/checks", True, False),
    ("c:\\x", True, False),
    ("Z:/", True, False),
    ("C:checks", False, False),  # (relative to the working folder of the drive C)
    ("C:", False, False),
    ("\\TrioForge\\checks", False, False),  # (rooted on the current drive)
    ("\\\\server\\share\\checks", True, False),
    ("//server/share/checks", True, True),
    ("\\\\server\\share", True, False),
    ("\\\\server", False, False),  # (a server is no share)
    ("\\\\server\\", False, False),
    ("//server", False, True),
    ("relative", False, False),
    ("./checks", False, False),
    ("../checks", False, False),
    ("~/checks", False, False),
    ("build\\checks", False, False),
    ("", False, False),
]


@pytest.mark.parametrize("value, windows, elsewhere", ABSOLUTENESS)
def test_a_path_is_absolute_by_one_rule_for_each_kind_of_platform(value, windows, elsewhere):
    assert is_absolute(value, "win32") is windows
    for platform in ("linux", "darwin"):
        assert is_absolute(value, platform) is elsewhere


@pytest.mark.parametrize("value, windows, elsewhere", [case for case in ABSOLUTENESS if case[0] and not case[0].startswith(("//", "\\\\"))])  # (no test asks the network about a share)
def test_the_variable_is_refused_exactly_when_the_path_is_not_absolute(value, windows, elsewhere):
    for platform, absolute in (("win32", windows), ("linux", elsewhere)):
        if absolute:
            assert checks_dir({ENVIRONMENT_VARIABLE: value}, platform=platform, home=HOME) == Path(value.strip())
        else:
            with pytest.raises(ValueError, match="TRIOFORGE_CHECKS_DIR"):
                checks_dir({ENVIRONMENT_VARIABLE: value}, platform=platform, home=HOME)


def run_node(snippet: str, *arguments: str, **env: str) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if key != ENVIRONMENT_VARIABLE}
    environment.update(env)
    return subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", snippet, *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
        env=environment,
        timeout=120,
    )


ABSOLUTE_IN_NODE = (
    "import('./scripts/smoke_live.mjs').then((m) => {"
    " const answers = {};"
    " for (const [platform, value] of JSON.parse(process.argv[1])) answers[`${platform}|${value}`] = m.isAbsolutePath(value, platform);"
    " process.stdout.write(JSON.stringify(answers));"
    "})"
)
FOLDERS_IN_NODE = (
    "import('./scripts/smoke_live.mjs').then((m) => {"
    " const answers = {};"
    " for (const [platform, value] of JSON.parse(process.argv[1])) {"
    "   try { answers[`${platform}|${value}`] = m.checksDir({ TRIOFORGE_CHECKS_DIR: value }, platform, 'HOME'); } catch (error) { answers[`${platform}|${value}`] = null; }"
    " }"
    " process.stdout.write(JSON.stringify(answers));"
    "})"
)


def node_answers(snippet: str, asked: list[tuple[str, str]]) -> dict:
    done = run_node(snippet, json.dumps(asked))
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_node_and_python_agree_on_which_paths_are_absolute_for_each_kind_of_platform():
    need_node()
    asked = [(platform, value) for value, _, _ in ABSOLUTENESS for platform in ("win32", "linux", "darwin")]
    answers = node_answers(ABSOLUTE_IN_NODE, asked)
    for platform, value in asked:
        assert answers[f"{platform}|{value}"] is is_absolute(value, platform), (platform, value)


# ---- a folder inside a git work tree is refused: a stamp there would be a file of that checkout ---------------------------------------------------------------


def make_repositories(tmp_path: Path) -> dict[str, Path]:
    plain = tmp_path / "plain"
    plain.mkdir()
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    linked = tmp_path / "linked"  # (a worktree that was added with `git worktree add`: its .git is a file)
    linked.mkdir()
    (linked / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    return {"plain": plain, "repo": repo, "linked": linked}


def test_a_folder_in_a_git_work_tree_is_refused_however_deep_and_whether_or_not_it_is_there_yet(tmp_path):
    places = make_repositories(tmp_path)
    for root in (places["repo"], places["linked"]):
        for inner in (root, root / "build", root / "build" / "checks", root / "not" / "yet" / "made"):
            with pytest.raises(ValueError, match=r"TRIOFORGE_CHECKS_DIR .*git work tree"):
                checks_dir({ENVIRONMENT_VARIABLE: str(inner)}, platform=sys.platform, home=HOME)
    assert checks_dir({ENVIRONMENT_VARIABLE: str(places["plain"] / "checks")}, platform=sys.platform, home=HOME) == places["plain"] / "checks"


def test_the_default_folder_is_not_held_to_that_because_a_home_folder_can_be_a_repository_itself(tmp_path):
    home = tmp_path / "home"
    (home / ".git").mkdir(parents=True)
    assert checks_dir({}, platform=sys.platform, home=home) == home / ".local" / "state" / "trioforge" / "checks"


def test_node_and_python_agree_on_the_folders_that_are_in_a_git_work_tree(tmp_path):
    need_node()
    places = make_repositories(tmp_path)
    values = [str(places["plain"] / "checks"), str(places["repo"] / "build" / "checks"), str(places["linked"] / "checks"), str(places["repo"])]
    answers = node_answers(FOLDERS_IN_NODE, [(sys.platform, value) for value in values])
    for value in values:
        try:
            expected: str | None = str(checks_dir({ENVIRONMENT_VARIABLE: value}, platform=sys.platform, home=HOME))
        except ValueError:
            expected = None
        got = answers[f"{sys.platform}|{value}"]
        assert (got is None) is (expected is None), value
        if expected is not None:
            assert Path(got) == Path(expected)


# ---- a part that ends in a dot or a space: Windows reads the name without it, and Python and Node read the real path of such a name differently (S2) ----------------------

DOTTED = ["C:\\stamps\\j.\\x", "C:\\stamps\\j \\x", "C:\\stamps\\j.", "C:/stamps/j./x", "C:\\stamps\\...\\x", "C:\\stamps\\a \\"]  # (Windows paths that have such a part)
PLAIN_WINDOWS = ["C:\\stamps\\a.b\\c", "C:\\stamps\\.\\x", "C:\\stamps\\..\\x", "C:\\stamps\\.hidden", "C:\\stamps\\x\\", "C:/stamps/a.b"]  # (a dot inside a name, and the parts "." and "..")


@pytest.mark.parametrize("value", DOTTED)
def test_a_part_that_ends_in_a_dot_or_a_space_is_refused_for_a_windows_path_on_any_computer(value):
    with pytest.raises(ValueError, match=r"TRIOFORGE_CHECKS_DIR .*ends in a dot or a space"):
        checks_dir({ENVIRONMENT_VARIABLE: value}, platform="win32", home=HOME)


@pytest.mark.parametrize("value", PLAIN_WINDOWS)
def test_a_dot_inside_a_name_and_the_parts_dot_and_dot_dot_are_no_reason_to_refuse_a_windows_path(value):
    assert checks_dir({ENVIRONMENT_VARIABLE: value}, platform="win32", home=HOME) == Path(value)


def test_a_part_that_ends_in_a_dot_is_a_name_like_any_other_where_the_computer_is_not_a_windows_one():
    value = "/stamps/a./b"
    if sys.platform == "win32":  # (a path that Windows reads, whatever the platform that was given)
        with pytest.raises(ValueError, match="ends in a dot or a space"):
            checks_dir({ENVIRONMENT_VARIABLE: value}, platform="linux", home=HOME)
    else:
        assert checks_dir({ENVIRONMENT_VARIABLE: value}, platform="linux", home=HOME) == Path(value)


@pytest.mark.skipif(sys.platform != "win32", reason="the two real paths of a name with a trailing dot differ on Windows only")
def test_the_reviews_spelling_of_a_junction_with_a_dot_is_refused_by_name_before_any_real_path_is_asked(tmp_path):
    places = make_repositories(tmp_path)
    (places["repo"] / "build").mkdir()
    make_link(places["plain"] / "j", places["repo"] / "build")
    with pytest.raises(ValueError, match="ends in a dot or a space"):
        checks_dir({ENVIRONMENT_VARIABLE: f"{places['plain']}\\j.\\x"}, platform=sys.platform, home=HOME)


def test_node_and_python_agree_on_which_paths_have_a_part_that_ends_in_a_dot_or_a_space():
    need_node()
    asked = [(platform, value) for value in (*DOTTED, *PLAIN_WINDOWS, "/stamps/a./b", "/stamps/a.b") for platform in ("win32", "linux")]
    answers = node_answers(FOLDERS_IN_NODE, asked)
    for platform, value in asked:
        try:
            checks_dir({ENVIRONMENT_VARIABLE: value}, platform=platform, home=HOME)
            refused = False
        except ValueError:
            refused = True
        assert (answers[f"{platform}|{value}"] is None) is refused, (platform, value)


# ---- the shared module of the checks and the smoke check work out the same folder --------------------------------------------------------------------------


def test_the_checks_and_the_release_build_work_out_the_same_folder(monkeypatch, tmp_path):
    import checks_common as common

    assert common.default_folder() == checks_dir()  # (the variable is set by the fixture)
    monkeypatch.delenv(ENVIRONMENT_VARIABLE)
    assert common.default_folder() == checks_dir()
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, "relative/folder")
    with pytest.raises(ValueError, match="TRIOFORGE_CHECKS_DIR"):
        common.default_folder()


def test_the_smoke_check_works_out_the_folder_the_way_the_other_checks_do(monkeypatch, tmp_path):
    need_node()
    snippet = "import('./scripts/smoke_live.mjs').then((m) => process.stdout.write(m.checksDir()))"
    monkeypatch.delenv(ENVIRONMENT_VARIABLE)
    default = run_node(snippet)
    assert default.returncode == 0, default.stderr
    assert Path(default.stdout) == checks_dir()
    given = tmp_path / "given"
    named = run_node(snippet, **{ENVIRONMENT_VARIABLE: str(given)})
    assert named.returncode == 0, named.stderr
    assert Path(named.stdout) == given
    bad = run_node(snippet, **{ENVIRONMENT_VARIABLE: "relative/folder"})
    assert bad.returncode != 0 and "TRIOFORGE_CHECKS_DIR" in bad.stderr


def test_the_work_tree_question_is_asked_of_a_path_that_is_a_path_of_this_computer_and_not_of_one_that_is_not(monkeypatch):
    """A Windows path on a Linux runner is a relative name, which lies in the checkout and was refused as a path in a work tree: the guard is about folders of THIS computer. A path of another kind of
    platform that IS a path here (a rooted path such as /x on Windows is on the current drive: R5) is asked about as well."""
    asked = []
    monkeypatch.setattr(module, "in_a_work_tree", lambda folder: asked.append(folder) or True)  # (every folder that is asked about is in a work tree)
    foreign = "linux" if sys.platform == "win32" else "win32"
    here = Path(ABSOLUTE[foreign]).root != ""  # (rooted on this computer: /stamps on Windows is; C:\stamps on Linux is not)
    if here:
        with pytest.raises(ValueError, match="git work tree"):
            checks_dir({ENVIRONMENT_VARIABLE: ABSOLUTE[foreign]}, platform=foreign, home=HOME)
        assert asked == [Path(ABSOLUTE[foreign])]
    else:
        assert checks_dir({ENVIRONMENT_VARIABLE: ABSOLUTE[foreign]}, platform=foreign, home=HOME) == Path(ABSOLUTE[foreign])
        assert asked == []
    del asked[:]
    own = ABSOLUTE["win32"] if sys.platform == "win32" else ABSOLUTE["linux"]
    with pytest.raises(ValueError, match="git work tree"):
        checks_dir({ENVIRONMENT_VARIABLE: own}, platform=sys.platform, home=HOME)
    assert asked == [Path(own)]


def make_link(link: Path, target: Path) -> None:
    """A symbolic link (a junction on Windows when symbolic links are refused: it needs no privilege and is the same thing for a folder), or a skip."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("cannot make a symbolic link here")
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def test_a_junction_or_a_link_to_a_folder_in_a_work_tree_is_refused_whatever_it_is_called_and_whether_or_not_the_rest_is_there_yet(tmp_path):
    places = make_repositories(tmp_path)
    (places["repo"] / "build").mkdir()
    make_link(places["plain"] / "j", places["repo"] / "build")
    for inner in (places["plain"] / "j", places["plain"] / "j" / "x", places["plain"] / "j" / "not" / "yet" / "made"):
        with pytest.raises(ValueError, match=r"TRIOFORGE_CHECKS_DIR .*git work tree"):
            checks_dir({ENVIRONMENT_VARIABLE: str(inner)}, platform=sys.platform, home=HOME)
    outside = tmp_path / "outside"
    outside.mkdir()
    make_link(places["plain"] / "ok", outside)
    assert checks_dir({ENVIRONMENT_VARIABLE: str(places["plain"] / "ok" / "checks")}, platform=sys.platform, home=HOME) == places["plain"] / "ok" / "checks"  # (a link to a place that is no work tree is fine)


@pytest.mark.skipif(sys.platform != "win32", reason="a path with a root and no drive (/x, \\x) is a path on the current drive on Windows only")
@pytest.mark.parametrize("value", ["/some-folder/checks"])  # (no test asks the network about a share: // is left out)
def test_a_rooted_path_with_no_drive_is_guarded_on_windows_whatever_the_platform_that_is_given(monkeypatch, value):
    asked = []
    monkeypatch.setattr(module, "in_a_work_tree", lambda folder: asked.append(folder) or False)
    checks_dir({ENVIRONMENT_VARIABLE: value}, platform="linux", home=HOME)
    assert asked, "the guard was asked about it"
