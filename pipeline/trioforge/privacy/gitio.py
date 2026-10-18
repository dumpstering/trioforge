"""Thin, safe access to git for the privacy scanner.

All commands run in the repository root with ``-z`` output where paths are involved. Failures
raise ``ScanError`` with a fixed message: git's own error text can hold paths, and the scanner's
output must never carry a private name.

Every git command is run as ``git --no-replace-objects -c core.quotepath=false ...`` with
``GIT_NO_REPLACE_OBJECTS=1`` in its environment. A replacement object (``git replace``) makes git
show one object where another is stored; the scan must see what is stored, because that is what a
push sends. And a path is always the real text of the name, never a quoted, escaped form.

A read that comes back short, and a git process that ends with an error, are errors: the scan
never treats a missing piece of history as a clean one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass

# Placed before the git command: no replacement objects, and paths are not quoted.
GLOBAL_OPTIONS = ("--no-replace-objects", "-c", "core.quotepath=false")


class ScanError(Exception):
    """A configuration or environment problem (exit code 2). ``message`` is safe to print."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FileReadError(ScanError):
    """A file could not be read. ``path`` is the unmasked path; mask it before printing."""

    def __init__(self, path: str) -> None:
        super().__init__("cannot read file")
        self.path = path


def decode_name(raw: bytes) -> str:
    """A path or ref name from git; undecodable bytes survive as surrogate escapes."""
    return raw.decode("utf-8", "surrogateescape")


@dataclass(frozen=True)
class IndexEntry:
    mode: str
    oid: str
    stage: int
    path: str


class Git:
    def __init__(self, cwd: str | None = None) -> None:
        self.exe = shutil.which("git")
        if self.exe is None:
            raise ScanError("git not found")
        self.cwd = cwd
        self.env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1")

    def command(self, *args: str) -> list[str]:
        """The command line for ``git <args>``, with the options every call carries."""
        return [self.exe, *GLOBAL_OPTIONS, *args]

    def run(self, *args: str, input: bytes | None = None) -> bytes:
        try:
            done = subprocess.run(
                self.command(*args),
                cwd=self.cwd,
                env=self.env,
                input=input,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise ScanError("git not found") from error
        if done.returncode != 0:
            raise ScanError(f"git {args[0]} failed")
        return done.stdout

    def root(self) -> str | None:
        """The top-level directory of the repository that contains the working directory."""
        try:
            done = subprocess.run(
                self.command("rev-parse", "--show-toplevel"),
                cwd=self.cwd,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise ScanError("git not found") from error
        if done.returncode != 0:
            return None
        text = decode_name(done.stdout).strip("\r\n")
        return text or None

    def has_object(self, oid: str) -> bool:
        """Whether this repository holds the object ``oid``."""
        try:
            done = subprocess.run(
                self.command("cat-file", "-e", oid),
                cwd=self.cwd,
                env=self.env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise ScanError("git not found") from error
        return done.returncode == 0

    def nul_separated(self, *args: str) -> list[str]:
        return [decode_name(part) for part in self.run(*args).split(b"\0") if part]

    def lines(self, *args: str) -> list[str]:
        return [
            decode_name(line)
            for line in self.run(*args).replace(b"\r\n", b"\n").split(b"\n")
            if line
        ]

    def index_entries(self) -> list[IndexEntry]:
        """Every entry of the index (``git ls-files -s -z``)."""
        entries = []
        for record in self.run("ls-files", "-s", "-z").split(b"\0"):
            if not record:
                continue
            head, _, path = record.partition(b"\t")
            mode, oid, stage = head.decode("ascii").split(" ")
            entries.append(IndexEntry(mode, oid, int(stage), decode_name(path)))
        return entries

    def unmerged(self) -> bool:
        return bool(self.run("ls-files", "--unmerged", "-z").strip(b"\0"))

    def staged_names(self) -> list[str]:
        """The files an ordinary commit would add or change, renames under their new name.
        A change to a submodule is listed too, whatever ``diff.ignoreSubmodules`` says."""
        return self.nul_separated(
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--diff-filter=ACMRT",
            "--find-renames",
            "--no-ext-diff",
            "--ignore-submodules=none",
        )

    def untracked_names(self) -> list[str]:
        return self.nul_separated("ls-files", "-z", "--others", "--exclude-standard")

    def batch(self) -> "BatchReader":
        return BatchReader(self)


class _Blob:
    """File-like view of one object streamed from ``git cat-file --batch``."""

    def __init__(self, reader: "BatchReader", size: int) -> None:
        self._reader = reader
        self._left = size
        self._open = True

    def read(self, size: int = -1) -> bytes:
        if not self._open or self._left <= 0:
            return b""
        want = self._left if size is None or size < 0 else min(size, self._left)
        data = self._reader._take(want)
        if len(data) < want:
            self._left = 0
            raise ScanError("git object truncated")
        self._left -= len(data)
        return data

    def close(self) -> None:
        if self._open:
            self._open = False
            left, self._left = self._left, 0
            self._reader._finish(left)


class BatchReader:
    """One long-lived ``git cat-file --batch`` process; objects are read one at a time."""

    def __init__(self, git: Git) -> None:
        try:
            self._process = subprocess.Popen(
                git.command("cat-file", "--batch"),
                cwd=git.cwd,
                env=git.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise ScanError("git not found") from error
        self._current: _Blob | None = None

    def _take(self, size: int) -> bytes:
        chunks = []
        remaining = size
        while remaining > 0:
            part = self._process.stdout.read(remaining)
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        return b"".join(chunks)

    def _finish(self, unread: int) -> None:
        """Skip what the caller did not read, and the line feed that ends every object."""
        while unread > 0:
            part = self._process.stdout.read(min(unread, 1 << 20))
            if not part:
                raise ScanError("git object truncated")
            unread -= len(part)
        if self._process.stdout.read(1) != b"\n":
            raise ScanError("git object truncated")
        self._current = None

    def get(self, oid: str) -> tuple[str, _Blob]:
        """Return ``(type, blob)``; the previous blob is closed first."""
        if self._current is not None:
            self._current.close()
        try:
            self._process.stdin.write(oid.encode("ascii") + b"\n")
            self._process.stdin.flush()
        except OSError as error:
            raise ScanError("git cat-file failed") from error
        header = self._process.stdout.readline().split()
        if len(header) != 3:
            raise ScanError("git object missing")
        blob = _Blob(self, int(header[2]))
        self._current = blob
        return header[1].decode("ascii"), blob

    def close(self, check: bool = True) -> None:
        """Finish the process. With ``check``, a process that ended with an error, or an object
        left half read, is an error: the scan must not pass over a gap."""
        problem: ScanError | None = None
        try:
            if self._current is not None:
                self._current.close()
        except ScanError as error:
            problem = error
        try:
            self._process.stdin.close()
        except OSError:
            pass
        try:
            self._process.stdout.read()  # nothing is left in a good run; do not leave git blocked
        except (OSError, ValueError):
            pass
        status = self._process.wait()
        self._process.stdout.close()
        if check:
            if problem is not None:
                raise problem
            if status != 0:
                raise ScanError("git cat-file failed")

    def __enter__(self) -> "BatchReader":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close(check=exc_type is None)


def iter_pairs(items: list[str]) -> Iterator[tuple[str, str]]:
    """``oid`` or ``oid path`` lines of ``git rev-list --objects`` as ``(oid, path)``."""
    for item in items:
        oid, _, path = item.partition(" ")
        yield oid, path
