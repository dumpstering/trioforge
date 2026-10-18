"""Shared helpers and fixtures for the privacy scanner tests. This module holds no tests.

Test data uses only invented names (Zorblax, Quimmet, Vexandra, McHale, Brannoc, Ilsabet,
Corvane, Dathril, Testchar, Extraname). Every string shaped like a game-log line is built at
run time from pieces, so that no source line of the tests matches a log-shape rule: the
repository must pass its own scanner.

Digests are computed here with the standard library only (``h``), never with the code under
test, so the tests check the scanner against an independent reference.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import io
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from trioforge.privacy import scan as S

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "pipeline"

KEY_HEX = "00" * 32
KEY = bytes.fromhex(KEY_HEX)
OTHER_KEY_HEX = "11" * 32
OTHER_KEY = bytes.fromhex(OTHER_KEY_HEX)

HEADER_DENY = "# HMAC-SHA256 digests of private tokens; key is not in this repository"
HEADER_ALLOW = "# HMAC-SHA256 digests of reviewed harmless tokens"

# Every variable the --explain guard looks at; the helpers strip them from child environments.
CI_VARS = (
    "CI",
    "GITHUB_ACTIONS",
    "TF_BUILD",
    "BUILDKITE",
    "GITLAB_CI",
    "JENKINS_URL",
    "DRONE",
    "CIRCLECI",
    "TRAVIS",
    "APPVEYOR",
)

FINDING_LINE = re.compile(
    r"^(?P<path>.*):(?P<line>\d+):(?P<col>\d+): (?P<rule>[a-z-]+) \[(?P<tag>[^\]]*)\]$"
)


def h(token: str, key: bytes = KEY) -> str:
    """Reference digest: HMAC-SHA256 of the UTF-8 token, as lowercase hex."""
    return hmac.new(key, token.encode("utf-8"), hashlib.sha256).hexdigest()


def tag(token: str, key: bytes = KEY) -> str:
    return h(token, key)[:8]


def key_check(key: bytes = KEY) -> str:
    return h("trioforge-key-check", key)[:16]


DENY = frozenset({h("zorblax"), h("quimmet")})


# ---- log-shaped strings, built from pieces ---------------------------------------------


def tell_line(name: str = "Vexandra") -> str:
    return name + " tells you, 'hello'"


def loot_line(item: str = "a Rusty Dagger.") -> str:
    return "You have " + "looted " + item


def named_loot_line(name: str) -> str:
    return "--" + name + " has " + "looted a Bone Chip.--"


def who_line(name: str = "Vexandra") -> str:
    return "[50 Paladin] " + name + " (Ogre) <Guild>"


def timestamp_prefix() -> str:
    return "[" + "Mon Oct 13 19:53:47 2026" + "] "


# The first-person forms: what the client writes for the player's own chat.
SELF_FORMS = (
    "say",
    "shout",
    "auction",
    "say out of character",
    "say to your party",
    "tell your party",
    "tell the guild",
    "tell General:1",
)


def self_line(form: str = "say", text: str = "hello there") -> str:
    return "You " + form + ", '" + text + "'"


# Words the provenance rule looks for, built from pieces so that this file does not hold them.
PROVENANCE_WORDS = {
    "client name": "EQ" + "game",
    "client name in lower case": "eq" + "game",
    "code listing": "dis" + "assembler",
    "code listing, capitalised": "Disassem" + "bly",
    "address": "R" + "VA",
    "section": ".r" + "data",
}


def windows_profile(user: str, drive: str = "C", sep: str = "\\") -> str:
    return drive + ":" + sep + "Users" + sep + user


def gitbash_profile(user: str, drive: str = "c") -> str:
    return "/" + drive + "/" + "Users" + "/" + user


def posix_home(user: str) -> str:
    return "/" + "home" + "/" + user


# ---- scanning helpers --------------------------------------------------------------------


def scan(text, path="f.txt", deny=DENY, allow=frozenset(), key=KEY, **kwargs):
    return S.scan_text(path, text, key, set(deny), set(allow), **kwargs)


def scan_blob(path, data, deny=DENY, allow=frozenset(), key=KEY, **kwargs):
    return S.scan_paths([path], key, set(deny), set(allow), lambda p: data, **kwargs)


def rules(findings):
    return [f.rule for f in findings]


def parse_output(text: str):
    """The finding lines of a scan's stdout, as dicts."""
    found = []
    for raw in text.splitlines():
        match = FINDING_LINE.match(raw)
        if match:
            found.append(match.groupdict())
    return found


# ---- git helpers -------------------------------------------------------------------------

GIT_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_PREFIX")


def git(repo, *args, env=None, check=True, input=None):
    completed = subprocess.run(
        ["git", *map(str, args)], cwd=repo, env=env, input=input, capture_output=True
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"git {' '.join(map(str, args))} failed: "
            f"{completed.stderr.decode('utf-8', 'replace')}"
        )
    return completed


@pytest.fixture
def gitenv(tmp_path, monkeypatch):
    """Isolate git from the machine's configuration for this test (and its child processes)."""
    config = tmp_path / "empty.gitconfig"
    config.write_bytes(b"")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    # Never let git discover a repository above the test's temp directory.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    # The identity check refuses any commit date that is not in UTC, so test commits are made
    # in UTC whatever the machine's own time zone is.
    monkeypatch.setenv("TZ", "UTC")
    for name in GIT_VARS:
        monkeypatch.delenv(name, raising=False)
    for name in CI_VARS + ("TRIOFORGE_PRIVACY_KEY",):
        monkeypatch.delenv(name, raising=False)
    return dict(os.environ)


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "core.autocrlf", "false")
    return path


def write(repo: Path, relative: str, content) -> Path:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8") if isinstance(content, str) else content
    target.write_bytes(data)
    return target


def commit(repo, message, *extra):
    git(repo, "commit", "-q", "-m", message, *extra)


def privacy_files(
    repo: Path,
    *,
    deny=("zorblax", "quimmet"),
    allow=(),
    key: bytes = KEY,
    with_key_check=True,
    allow_lines=None,
    identity=None,
):
    """Write privacy/denylist.hmac and allow.hmac the way the private builder would. With
    ``identity`` (an address) it also writes privacy/identity.txt."""
    if identity is not None:
        write(repo, "privacy/identity.txt", identity + "\n")
    lines = [HEADER_DENY]
    if with_key_check:
        lines.append("# key-check: " + key_check(key))
    lines += sorted(h(token, key) for token in deny)
    write(repo, "privacy/denylist.hmac", "\n".join(lines) + "\n")
    write(
        repo,
        "privacy/allow.hmac",
        "\n".join([HEADER_ALLOW, *sorted(h(token, key) for token in allow)]) + "\n",
    )
    if allow_lines is not None:
        header = (
            "# reviewed exceptions for log-shape rules: "
            "<path>\\t<rule>\\t<sha256 of the exact line>"
        )
        body = ["\t".join(entry) for entry in allow_lines]
        write(repo, "privacy/allowlist-lines.txt", "\n".join([header, *body]) + "\n")


def write_key_file(directory: Path, text: str | bytes = KEY_HEX + "\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "privacy.key"
    target.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return target


@pytest.fixture
def repo(tmp_path, gitenv):
    """A temp git repository holding privacy/ files built for the test key."""
    root = make_repo(tmp_path / "work")
    privacy_files(root)
    return root


@pytest.fixture
def keyfile(tmp_path):
    return write_key_file(tmp_path / "keys")


# ---- running the CLI -----------------------------------------------------------------


def cli_env(extra=None):
    env = dict(os.environ)
    for name in CI_VARS + ("TRIOFORGE_PRIVACY_KEY",):
        env.pop(name, None)
    env["PYTHONPATH"] = str(PIPELINE)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra or {})
    return env


def run_cli(args, cwd, *, env=None, input=None, process=False):
    """Run the command line and return an object with ``returncode``, ``stdout`` and ``stderr``.

    By default the scanner's ``main`` runs inside this process, with an empty environment and no
    default key file: starting Python costs seconds on some machines, and a hundred of these
    runs would dominate the suite. With ``process=True``, or when ``env`` or ``input`` is given,
    ``python -m trioforge.privacy.scan`` runs in a child process instead.
    """
    if env is None and input is None and not process:
        code, out, err = call_main(args, cwd=cwd)
        return types.SimpleNamespace(returncode=code, stdout=out, stderr=err)
    return subprocess.run(
        [sys.executable, "-m", "trioforge.privacy.scan", *map(str, args)],
        cwd=cwd,
        env=cli_env() if env is None else env,
        input=input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class FakeTty(io.StringIO):
    def isatty(self):
        return True


@contextlib.contextmanager
def chdir(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def call_main(args, *, cwd=None, env=None, tty=False, default_key_file=None, stdin=None):
    """Run the CLI in this process; returns (exit code, stdout text, stderr text). ``stdin`` is
    the text the scanner reads as its standard input (the ref lines of a push)."""
    out = FakeTty() if tty else io.StringIO()
    err = io.StringIO()
    scope = chdir(cwd) if cwd is not None else contextlib.nullcontext()
    extra = {} if stdin is None else {"stdin": io.StringIO(stdin)}
    with scope:
        code = S.main(
            [str(a) for a in args],
            env={} if env is None else env,
            stdout=out,
            stderr=err,
            default_key_file=default_key_file,
            **extra,
        )
    return code, out.getvalue(), err.getvalue()


def find_sh():
    import shutil

    found = shutil.which("sh")
    if found:
        return found
    git_exe = shutil.which("git")
    if git_exe:
        base = Path(git_exe).resolve().parent
        for parent in (base, base.parent, base.parent.parent):
            candidate = parent / "usr" / "bin" / "sh.exe"
            if candidate.exists():
                return str(candidate)
    return None
