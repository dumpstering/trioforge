"""Fetch item pages from eqlwiki.com through its API.

Three things live here:

* :func:`list_category` lists the pages of a category;
* :func:`fetch_pages` fetches the wikitext of pages by id, 50 to a request;
* a command line for the two jobs the pipeline needs::

      python -m trioforge.sources.eqlwiki fetch --out sources/eqlwiki/2026-10-13 [--resume]
      python -m trioforge.sources.eqlwiki record --out fixtures/wiki "Page title" ...

``fetch`` pulls every page of a category (default ``Category:Items``) into

* ``raw/members.json``: ``{"category": ..., "members": [{"pageid", "title"}, ...]}``;
* ``raw/batch-0000.json.gz``, ...: ``{"batch": n, "pageids": [...], "pages": [...]}``, one
  record per page id of the batch, in order, each ``{"pageid", "ns", "title", "revid",
  "timestamp", "content"}`` (a page the wiki no longer has is ``{..., "missing": true}`` with
  null revid, timestamp and content);
* ``manifest.json``: ``{"date", "category", "members", "batches", "pages", "missing"}``, written
  last, so its presence means the run finished. ``pages + missing == members``.

``--resume`` continues an interrupted run: it keeps the saved member list (so the batches are
cut the same way as before) and skips each batch file that exists, parses, and holds exactly the
page ids it should. A resumed run writes the same bytes as one clean run. Files are written to a
temporary name and renamed, so a Ctrl-C never leaves a half-written batch.

``record`` saves the raw API reply for each given title (one request each, redirects not
followed) as ``<slug>.json``: that is how ``fixtures/wiki`` was made.

Everything goes through :class:`trioforge.sources.http.PoliteClient`: one request a second.

**One run at a time.** The politeness is per process, so two runs at once would ask the wiki for two
requests a second. A run takes an exclusive lock for the API host before its first request and holds it
for the whole run (:class:`FetchLock`); a second run exits 2 with "another fetch is running". The hold is an
**operating-system lock on the open lock file** (``msvcrt.locking`` on Windows, ``fcntl.flock`` elsewhere),
so there is nothing to take over: the system lets go of it when the run ends or dies, and two runs that find
the same stale file cannot both get the lock. The file ``sources/.eqlwiki.lock`` only holds the process id
of the run, for the message. The temporary files of a write have names of their own, so a leftover can never
be mistaken for another run's.
"""

from __future__ import annotations

import argparse
import errno
import gzip
import json
import os
import re
import secrets
import sys
import time
import unicodedata
import zlib
from collections.abc import Iterator, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .http import API_URL, FetchError, PoliteClient

__all__ = [
    "BATCH_SIZE",
    "DEFAULT_CATEGORY",
    "LOCK_PATH",
    "REPO_ROOT",
    "USER_AGENT",
    "FetchLock",
    "fetch_pages",
    "fixture_slug",
    "list_category",
    "main",
    "page_records",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "sources" / ".eqlwiki.lock"  # one lock for the API host, whatever --out says
STALE_UNREADABLE_SECONDS = 10.0  # a lock file with no readable process id is a crash this old, or a run still writing it
_LOCK_OFFSET = 1 << 30  # Windows: the byte that is locked lies far beyond the text, so the process id stays readable
_BINARY = getattr(os, "O_BINARY", 0)  # Windows opens files in text mode unless told not to

# No URL until the public project account exists: never a dead link, never someone else's.
USER_AGENT = "TrioForge-extractor/0.1 (+https://github.com/dumpstering/trioforge; non-commercial fan project; 1 request/s)"
DEFAULT_CATEGORY = "Category:Items"
BATCH_SIZE = 50  # the most pages with content that the API gives one request
PROGRESS_EVERY = 10  # batches
CATEGORY_LIMIT = 500  # the most members the API lists in one reply

_REVISION_PARAMS = {
    "action": "query",
    "prop": "revisions",
    "rvprop": "ids|timestamp|content",
    "rvslots": "main",
}


# ---- the API ------------------------------------------------------------------------------


def _continuation(response: dict, seen: set, base: dict) -> dict | None:
    """The parameters for the next request of a continued query, or None when it is done.

    Raises FetchError if the wiki hands back a continuation it already gave: that would loop
    forever, one request a second.
    """
    cont = response.get("continue")
    if not cont:
        return None
    token = tuple(sorted((str(key), str(value)) for key, value in cont.items()))
    if token in seen:
        raise FetchError(API_URL, None, "the wiki repeated a continuation token")
    seen.add(token)
    return {**base, **cont}


def list_category(client: PoliteClient, title: str) -> list[dict]:
    """The main-namespace pages of a category, in the wiki's order, as ``{"pageid", "title"}``."""
    base = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": title,
        "cmtype": "page",
        "cmlimit": CATEGORY_LIMIT,
        "cmnamespace": 0,
    }
    members: list[dict] = []
    params: dict | None = base
    seen: set = set()
    while params is not None:
        response = client.get_json(params)
        for entry in (response.get("query") or {}).get("categorymembers", []):
            members.append({"pageid": int(entry["pageid"]), "title": str(entry["title"])})
        params = _continuation(response, seen, base)
    return members


def _missing(pageid: int | None, title: str | None = None, ns: int | None = None) -> dict:
    return {
        "pageid": pageid,
        "ns": ns,
        "title": title,
        "revid": None,
        "timestamp": None,
        "content": None,
        "missing": True,
    }


def _record(page: dict) -> dict:
    revisions = page.get("revisions") or []
    if page.get("missing") or page.get("invalid") or not revisions:
        return _missing(page.get("pageid"), page.get("title"), page.get("ns"))
    revision = revisions[0]
    content = ((revision.get("slots") or {}).get("main") or {}).get("content")
    return {
        "pageid": page["pageid"],
        "ns": page.get("ns"),
        "title": page.get("title"),
        "revid": revision.get("revid"),
        "timestamp": revision.get("timestamp"),
        "content": content if isinstance(content, str) else "",  # hidden text: an empty page
    }


def page_records(response: dict) -> list[dict]:
    """The page records of one ``prop=revisions`` reply (formatversion 2), in reply order.

    A page that is missing, invalid or has no revision comes back as a ``missing`` record.
    """
    return [_record(page) for page in (response.get("query") or {}).get("pages", [])]


def _fetch_batch(client: PoliteClient, ids: list[int]) -> list[dict]:
    """One record per id, in the order asked. Follows a continued reply to its end."""
    base = {**_REVISION_PARAMS, "pageids": "|".join(str(pageid) for pageid in ids)}
    found: dict[int, dict] = {}
    params: dict | None = base
    seen: set = set()
    while params is not None:
        response = client.get_json(params)
        for record in page_records(response):
            if not record.get("missing") and record["pageid"] not in found:
                found[record["pageid"]] = record
        params = _continuation(response, seen, base)
    return [found.get(pageid) or _missing(pageid) for pageid in ids]


def fetch_pages(client: PoliteClient, pageids: Sequence[int], batch: int = BATCH_SIZE) -> Iterator[dict]:
    """Yield the record of every page id, in order, fetching ``batch`` (at most 50) at a time.

    A page the wiki does not have is yielded as a record with ``"missing": True``.
    """
    if not 1 <= batch <= BATCH_SIZE:
        raise ValueError(f"batch must be between 1 and {BATCH_SIZE}, not {batch}")
    ids = [int(pageid) for pageid in pageids]

    def records() -> Iterator[dict]:
        for start in range(0, len(ids), batch):
            yield from _fetch_batch(client, ids[start : start + batch])

    return records()


# ---- files ----------------------------------------------------------------------------------


def _atomic_write(path: Path, data: bytes) -> None:
    """Write to a temporary name and rename, so a reader never sees half a file.

    The temporary name is unique to this write (process id and a random part), so two writers can never
    share one and a leftover can never be mistaken for another run's.
    """
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(value: Any, *, indent: int | None = None) -> bytes:
    # ensure_ascii keeps the raw text faithful and safe to write, whatever the wiki sent.
    separators = (",", ":") if indent is None else None
    return (json.dumps(value, indent=indent, separators=separators) + "\n").encode("ascii")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _is_member_file(saved: Any) -> bool:
    """True for a parsed members.json of the shape this module writes."""
    return (
        isinstance(saved, dict)
        and isinstance(saved.get("category"), str)
        and isinstance(saved.get("members"), list)
        and all(
            isinstance(member, dict) and isinstance(member.get("pageid"), int) for member in saved["members"]
        )
    )


def _batch_path(raw: Path, index: int) -> Path:
    return raw / f"batch-{index:04d}.json.gz"


def _write_batch(path: Path, index: int, ids: list[int], pages: list[dict]) -> None:
    data = _json_bytes({"batch": index, "pageids": ids, "pages": pages})
    _atomic_write(path, gzip.compress(data, compresslevel=9, mtime=0))  # mtime 0: same bytes every run


def _load_batch(path: Path, index: int, ids: list[int]) -> dict | None:
    """The batch file's content if it parses and holds exactly these page ids, else None."""
    try:
        data = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, EOFError, ValueError, zlib.error):
        return None
    if not isinstance(data, dict) or data.get("batch") != index or data.get("pageids") != ids:
        return None
    pages = data.get("pages")
    if not isinstance(pages, list) or [p.get("pageid") if isinstance(p, dict) else None for p in pages] != ids:
        return None
    return data


def _snapshot_date(out: Path, today: date) -> str:
    """The date a fetch is filed under: the directory's own name if it is a date, else today."""
    name = out.resolve().name
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", name):
        try:
            return date.fromisoformat(name).isoformat()
        except ValueError:
            pass
    return today.isoformat()


def _stale_batches(raw: Path, batches: int) -> list[Path]:
    stale = []
    for path in raw.glob("batch-*.json.gz"):
        match = re.fullmatch(r"batch-(\d{4,})\.json\.gz", path.name)
        if match and int(match.group(1)) >= batches:
            stale.append(path)
    return stale


class _Refusal(Exception):
    """The command line asked for something that would mix up two runs."""


def _pid_alive(pid: int) -> bool:
    """True if a process with this id is running (or cannot be told apart from one: when unsure, say yes).

    On Windows this asks the process for its exit code. It never uses ``os.kill(pid, 0)`` there: Windows
    would end the process.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        error_access_denied = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() == error_access_denied  # it exists, we may not ask about it
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _lock_file(descriptor: int) -> bool:
    """Take the operating-system lock on an open file without waiting. False if another handle holds it.

    On Windows the lock is one byte far beyond the end of the file (``msvcrt.locking`` locks from the current
    position), so that other runs can still read the process id; there a handle is refused even in the same
    process. ``fcntl.flock`` locks the whole open file description, so a second ``open`` is refused too.
    Any other failure (a file system that cannot lock) is raised as the ``OSError`` it is.
    """
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, _LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EDEADLK):
                return False
            raise
        return True
    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
            return False
        raise
    return True


def _unlock_file(descriptor: int) -> None:
    """Give the operating-system lock back (closing the file would too). Never raises."""
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, _LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        pass


class FetchLock:
    """An exclusive lock for the whole fetch: the lock file, locked by the operating system while this run lives.

    ``with FetchLock(path):`` takes the lock or raises :class:`_Refusal` ("another fetch is running"). The
    file is opened (made, if it is not there) and an OS lock is taken on the open handle, without waiting: if
    another run holds it, the answer is no, whatever the file says. The lock is the system's, so it ends with
    the run, and a crash leaves nothing to take over, only a file whose lock is free. Two runs that find the same
    stale file cannot both get the lock, and nobody deletes a file that another run has just made.

    The file also holds the process id of the run, for the message. A file that is not locked but names a process
    that is running, or that holds no readable id and is younger than ``STALE_UNREADABLE_SECONDS``, is still
    respected, because an older version of this program (which locked nothing) may have made it. The lock file is
    removed at the end, but only if it still holds this run's id.
    """

    def __init__(self, path: Path, *, pid: int | None = None, alive=None) -> None:
        self.path = Path(path)
        self.pid = os.getpid() if pid is None else pid
        self._alive = _pid_alive if alive is None else alive
        self._held = False
        self._descriptor: int | None = None

    def _refuse(self, owner: int | None) -> _Refusal:
        who = f"process {owner}" if owner is not None else "a process that wrote no readable id"
        return _Refusal(
            f"another fetch is running ({who}); wait for it to finish, "
            f"or delete {self.path} if you are sure no fetch is running"
        )

    def _owner(self) -> int | None:
        """The process id the lock file holds, or None if it is missing, empty or not an id."""
        try:
            text = self.path.read_text(encoding="ascii").strip()
        except (OSError, ValueError):
            return None
        return int(text) if text.isascii() and text.isdigit() and len(text) <= 12 else None

    def _cannot(self, error: OSError) -> _Refusal:
        return _Refusal(f"cannot take the lock file {self.path}: {error.strerror or type(error).__name__}")

    def _take_os_lock(self, descriptor: int) -> bool:
        """The OS lock on the open file: True if this run has it now, False if another handle holds it."""
        try:
            return _lock_file(descriptor)
        except OSError as error:
            raise self._cannot(error) from None

    def _is_the_file_at_the_path(self, descriptor: int) -> bool:
        """False if the path now names another file than the one that was opened (it was removed and made again)."""
        try:
            there = os.stat(self.path)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise self._cannot(error) from None
        opened = os.fstat(descriptor)
        return (there.st_ino, there.st_dev) == (opened.st_ino, opened.st_dev)

    def _check_what_the_file_says(self, descriptor: int) -> None:
        """The lock is free, but a file written by a run of an older version may still name a live run."""
        owner = self._owner()
        if owner is not None and self._alive(owner):
            raise self._refuse(owner)
        if owner is None:
            try:
                age = time.time() - os.fstat(descriptor).st_mtime
            except OSError as error:
                raise self._cannot(error) from None
            if age < STALE_UNREADABLE_SECONDS:
                raise self._refuse(None)

    def _write_owner(self, descriptor: int) -> None:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"{self.pid}\n".encode("ascii"))
        except OSError as error:
            raise self._cannot(error) from None

    def _let_go(self, descriptor: int, *, locked: bool) -> None:
        if locked:
            _unlock_file(descriptor)
        try:
            os.close(descriptor)
        except OSError:
            pass

    def acquire(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise self._cannot(error) from None
        for _ in range(5):  # open (making the file if need be); if the file changes under us, start again
            made = False
            try:
                descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | _BINARY)
                made = True
            except FileExistsError:
                try:
                    descriptor = os.open(self.path, os.O_RDWR | _BINARY)
                except FileNotFoundError:
                    continue  # it went away between the two calls
                except OSError as error:
                    raise self._cannot(error) from None
            except OSError as error:
                raise self._cannot(error) from None
            locked = False
            try:
                locked = self._take_os_lock(descriptor)
                if not locked:
                    raise self._refuse(self._owner())
                if not self._is_the_file_at_the_path(descriptor):
                    self._let_go(descriptor, locked=True)
                    continue
                if not made:
                    self._check_what_the_file_says(descriptor)
                self._write_owner(descriptor)
            except BaseException:
                self._let_go(descriptor, locked=locked)
                raise
            self._descriptor = descriptor
            self._held = True
            return
        raise self._refuse(None)

    def _remove(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass  # gone already, or (Windows) another run has opened it: then it is right that it stays

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        descriptor, self._descriptor = self._descriptor, None
        ours = self._owner() == self.pid  # never remove a lock file that names somebody else now
        if descriptor is None:
            return
        if os.name != "nt" and ours:
            self._remove()  # while the lock is still held: a run that opened this file earlier sees it is gone
        self._let_go(descriptor, locked=True)
        if os.name == "nt" and ours:
            self._remove()  # Windows cannot delete an open file; if another run has it open the removal fails, rightly

    def __enter__(self) -> FetchLock:
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def run_fetch(
    client: PoliteClient,
    out: Path,
    category: str,
    resume: bool,
    today: date,
    say=print,
) -> dict:
    """Fetch a whole category into ``out`` (see the module docstring). Returns the manifest."""
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").unlink(missing_ok=True)  # no manifest while the run is unfinished

    members_path = raw / "members.json"
    members = None
    if resume:
        saved = _read_json(members_path)
        if _is_member_file(saved):
            if saved["category"] != category:
                raise _Refusal(
                    f"{members_path} was fetched for {saved['category']}, not {category}; "
                    "use another --out directory"
                )
            members = saved["members"]
    if members is None:
        members = list_category(client, category)
        _atomic_write(members_path, _json_bytes({"category": category, "members": members}, indent=1))

    ids = [member["pageid"] for member in members]
    chunks = [ids[start : start + BATCH_SIZE] for start in range(0, len(ids), BATCH_SIZE)]
    for path in _stale_batches(raw, len(chunks)):
        path.unlink()

    pages = missing = 0
    for index, chunk in enumerate(chunks):
        path = _batch_path(raw, index)
        data = _load_batch(path, index, chunk) if resume else None
        if data is None:
            records = _fetch_batch(client, chunk)
            _write_batch(path, index, chunk, records)
        else:
            records = data["pages"]
        missing += sum(1 for record in records if record.get("missing"))
        pages += sum(1 for record in records if not record.get("missing"))
        done = index + 1
        if done % PROGRESS_EVERY == 0:
            say(f"batch {done}/{len(chunks)}")

    manifest = {
        "date": _snapshot_date(out, today),
        "category": category,
        "members": len(members),
        "batches": len(chunks),
        "pages": pages,
        "missing": missing,
    }
    _atomic_write(out / "manifest.json", _json_bytes(manifest, indent=1))
    say(f"done: {len(members)} members, {pages} pages, {missing} missing, in {len(chunks)} batches -> {out}")
    return manifest


def fixture_slug(title: str) -> str:
    """A file name for a page title: lowercase ASCII words joined by hyphens."""
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower().replace("'", "")).strip("-")


def run_record(client: PoliteClient, titles: Sequence[str], out: Path, say=print) -> list[Path]:
    """Save the raw API reply for each title, one request per title, to ``out/<slug>.json``."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for title in titles:
        response = client.get_json({**_REVISION_PARAMS, "titles": title})
        path = out / f"{fixture_slug(title)}.json"
        _atomic_write(path, _json_bytes(response, indent=1))
        written.append(path)
        for record in page_records(response):
            state = "missing" if record.get("missing") else f"revid {record['revid']}"
            say(f"{title}\tpageid {record['pageid']}\t{state}")
    return written


# ---- command line -------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trioforge.sources.eqlwiki",
        description="Fetch pages from eqlwiki.com, politely (one request a second).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="fetch every page of a category into a dated directory")
    fetch.add_argument("--out", required=True, type=Path, help="e.g. sources/eqlwiki/2026-10-13")
    fetch.add_argument("--category", default=DEFAULT_CATEGORY)
    fetch.add_argument("--resume", action="store_true", help="continue an interrupted run")
    record = commands.add_parser("record", help="save the raw API reply for some page titles")
    record.add_argument("--out", required=True, type=Path, help="e.g. fixtures/wiki")
    record.add_argument("titles", nargs="+", metavar="TITLE")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client: PoliteClient | None = None,
    today: date | None = None,
) -> int:
    """The command line. Returns the exit code: 0 done, 2 failed (re-run with --resume), 130 Ctrl-C."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "record":
        slugs = [fixture_slug(title) for title in args.titles]
        if not all(slugs):
            parser.error("every title needs at least one ASCII letter or digit to make a file name")
        if len(set(slugs)) != len(slugs):
            parser.error("two of the titles would be saved to the same file")
    client = client or PoliteClient(USER_AGENT)
    today = today or datetime.now(timezone.utc).date()
    try:
        with FetchLock(LOCK_PATH):  # held for the whole run; LOCK_PATH is read now so a test can replace it
            if args.command == "fetch":
                run_fetch(client, args.out, args.category, args.resume, today)
            else:
                run_record(client, args.titles, args.out)
    except FetchError as error:
        print(f"error: {error}", file=sys.stderr)
        if args.command == "fetch":
            print("Nothing was lost: run the same command again with --resume to continue.", file=sys.stderr)
        return 2
    except _Refusal as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        if args.command == "fetch":
            print("interrupted: run the same command again with --resume to continue.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
