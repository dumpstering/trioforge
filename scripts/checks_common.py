"""The pieces that the scheduled checks of the maintainer's computer share: ``scripts/sources_check.py`` and ``scripts/pins_check.py``.

* **A polite fetcher** (:class:`Fetcher`). One request at a time, never two request *starts* less than a second apart (whatever the host, and the request for a
  robots.txt counts like any other); the project's own user agent, which names the project and a page of its site that says who runs it (:func:`user_agent`); nothing followed
  (a redirect is an answer that is not a 200); the robots.txt of a host is read once and honoured before a path of it is asked for, by the rules of RFC 9309
  (:func:`parse_robots`), with a ``Crawl-delay`` respected when it is longer than a second.
* **"Unreachable", never "changed".** A request that fails, an answer that is not a 200, a body that is too large or damaged, and an answer that is not JSON where
  JSON is expected, are all :class:`Unreachable`. The reason names the kind of failure (``HTTP 503``, ``TimeoutError``, ``the answer is not JSON``) and never
  carries text of the answer, which is a stranger's.
* **Stamps, logs and files.** ``<name>.last-run`` holds a UTC time to the second, the form that ``trioforge.precompute.release.scheduled_warnings`` reads
  (:func:`write_stamp`), in one folder outside every worktree that the release build reads too (:func:`default_folder`); ``<name>.log`` gets one line for each run, the
  last 200 kept (:func:`append_log`, :func:`run_main`), because a task under ``pythonw`` has no window to show a refusal or a crash in; every file is written whole or not at all (:func:`write_text_atomic`); a title from a wiki is shown as a code span that it cannot break out
  of (:func:`code_span`).
* **A dry run** (:class:`ReplayTransport`, :class:`VirtualTime`). Recorded answers in a folder stand in for the network, and a clock that only moves when the code
  sleeps stands in for time, so a check can be tried with no network and without waiting.

Standard library only: a scheduled task runs these files with the project's Python and nothing else installed or on the path.
"""

from __future__ import annotations

import argparse
import datetime
import http.client
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

PRODUCT = "TrioForge-checks"  # the name robots.txt knows this program by
VERSION = "0.1"
DEFAULT_CONTACT = "https://trioforge.pages.dev/about/"  # what the user agent points to: the about page of the site (the repository is private until it is made public, and its issues a 404)
MAX_CONTACT_LENGTH = 200
MIN_INTERVAL = 1.0  # seconds between the starts of two requests: the most that a check ever asks of anyone
MAX_CRAWL_DELAY = 60.0  # a host that asks for more between requests than this is left alone for the run
MAX_ROBOTS_REDIRECTS = 5  # the moves of a robots.txt that are followed (RFC 9309 has a crawler follow at least five)
REFUSALS = (401, 403, 429)  # the answers that mean that the host does not want to be asked: it is not asked again in the run, whatever Retry-After says
TIMEOUT = 60.0
MAX_BODY_BYTES = 64 * 1024 * 1024  # an answer over this, packed or unpacked, is refused
STAMP_SUFFIX = ".last-run"
MAX_REPORTS_A_SECOND = 99  # runs of one check that begin in the same second, which no schedule does
LOG_SUFFIX = ".log"
LOG_LINES = 200  # a log keeps this many of its last lines
MAX_LOG_TEXT = 400  # the longest text of a line of a log
OUTCOMES = ("ok", "failed", "refused", "error", "interrupted")  # how a run can end, as a log says it

_NOT_FOR_A_HEADER = re.compile(r"""[^\x21-\x7e]|[;()<>"'\\]""")  # a space, a control or non-ASCII character, and the signs that would end the comment of a user agent
_NETWORK_ERRORS = (OSError, http.client.HTTPException)  # (URLError, timeouts and resets are OSErrors; a cut-short answer is an http.client error)
_GZIP_MAGIC = b"\x1f\x8b"
_MOVED = (301, 302, 303, 307, 308)  # the answers that send the client elsewhere

Transport = Callable[[str, Mapping[str, str]], "tuple[int, Mapping[str, str], bytes]"]


# ---- who is asking ---------------------------------------------------------------------------------------------------------------------------------------


def check_contact(contact: object) -> str:
    """The page of the site that the user agent points a reader to, checked: an http or https address with a host and no user name, of plain ASCII without a space, and
    without the signs that would end the comment of a user agent (a semicolon, a parenthesis, an angle bracket, a quote or a backslash). Anything else is a ``ValueError``."""
    plain = isinstance(contact, str) and 0 < len(contact) <= MAX_CONTACT_LENGTH and _NOT_FOR_A_HEADER.search(contact) is None
    try:
        parts = urllib.parse.urlsplit(contact) if plain else None
        valid = parts is not None and parts.scheme in ("http", "https") and bool(parts.hostname) and parts.username is None and parts.password is None
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            f"the contact must be an http or https address of plain ASCII with a host and no user name, no space, no semicolon, parenthesis, angle bracket, quote or backslash "
            f"({MAX_CONTACT_LENGTH} characters at most)"
        )
    return str(contact)


def user_agent(contact: object = DEFAULT_CONTACT) -> str:
    """The user agent of the checks: the project, its version, a page of its site that says who runs it, and how fast it goes."""
    return f"{PRODUCT}/{VERSION} (+{check_contact(contact)}; non-commercial fan project; 1 request/s)"


# ---- what an answer can be ---------------------------------------------------------------------------------------------------------------------------------


class Unreachable(Exception):
    """A source could not be read as it should be, and so nothing is known of it: it is never taken for a change.

    ``reason`` is one short line made of the kind of failure; it never holds text of the answer.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Reply(NamedTuple):
    status: int
    headers: dict[str, str]  # the names in lower case
    body: bytes  # as the server sent it, unpacked if it was gzip


class _TooLarge(Exception):
    pass


def _unpack(body: bytes, encoding: str | None, limit: int) -> bytes:
    """The body unpacked, if it is gzip (by its header or by its first bytes): every member of the stream, at most ``limit`` bytes together."""
    if (encoding or "").strip().lower() != "gzip" and body[:2] != _GZIP_MAGIC:
        return body
    parts: list[bytes] = []
    total = 0
    while body:
        inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
        part = inflater.decompress(body, limit + 1 - total)  # (a limit of 0 would mean "no limit")
        total += len(part)
        if total > limit:
            raise _TooLarge
        if not inflater.eof:
            raise ValueError("the gzip stream is cut short")
        parts.append(part)
        body = inflater.unused_data.lstrip(b"\x00")  # (a gzip file may be padded with zeros)
        if body and body[:2] != _GZIP_MAGIC:
            raise ValueError("bytes after the gzip stream")
    return b"".join(parts)


def decode_json(body: bytes) -> Any:
    """The JSON value of a body, or :class:`Unreachable`: HTML where JSON was expected, a cut-short document, bytes that are not UTF-8, ``NaN`` and the like."""

    def refuse(constant: str) -> Any:
        raise ValueError(constant)

    try:
        return json.loads(body.decode("utf-8-sig"), parse_constant=refuse)
    except (ValueError, RecursionError):
        raise Unreachable("the answer is not JSON") from None


# ---- robots.txt ------------------------------------------------------------------------------------------------------------------------------------------


def _shared(name: str) -> Any:
    """A standard-library module of ``pipeline/trioforge/sources`` that the checks share with the fetchers of the sources, loaded by its path (as ``default_folder`` loads
    ``checks_dir``: no installed copy of the package is needed, and none can be stale)."""
    path = Path(__file__).resolve().parents[1] / "pipeline" / "trioforge" / "sources" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"trioforge_{name}_of_the_scripts", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot find {path.name} of the sources")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_robots = _shared("robots")
Robots = _robots.Robots  # (one reading of a robots.txt, by the rules of RFC 9309, for the checks and for the fetchers of the sources alike)
_complete = _robots.check_complete


def parse_robots(text: str, product: str = PRODUCT) -> Robots:
    """The :class:`Robots` of a robots.txt for the program called ``product`` (see ``trioforge.sources.robots``)."""
    return _robots.parse_robots(text, product)


# ---- the fetcher -----------------------------------------------------------------------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect handler that follows nothing: urllib then raises ``HTTPError`` with the 3xx status, which is an answer that is not a 200."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def real_transport(timeout: float = TIMEOUT) -> Transport:
    """The transport of a real run: ``transport(url, headers) -> (status, headers, body)`` by urllib. An HTTP error status is an answer; a redirect is not followed;
    only http and https addresses are asked for. The body of a 200 that stops before its Content-Length raises :class:`http.client.IncompleteRead` (the fetcher calls it
    unreachable). **The body of any other answer is never read and never used** -- a 401, 403 or 429 is a refusal whatever happens to its body, and a stalled or cut one must not
    hide that from the fetcher, which would then ask the host again -- so it is handed on as ``b""``."""

    def transport(url: str, headers: Mapping[str, str]) -> tuple[int, dict[str, str], bytes]:
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            raise ValueError("only http and https addresses are asked for")
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            with _OPENER.open(request, timeout=timeout) as response:
                reply_headers = dict(response.headers.items())
                if response.status != 200:
                    return response.status, reply_headers, b""
                body = response.read(MAX_BODY_BYTES + 1)
                _complete(response.status, reply_headers, body)
                return response.status, reply_headers, body
        except urllib.error.HTTPError as error:
            try:
                reply_headers = dict(error.headers.items()) if error.headers else {}
            finally:
                error.close()
            return error.code, reply_headers, b""

    return transport


class Fetcher:
    """GET requests, politely: serial, a second apart, with the project's user agent, and robots.txt honoured (see the module's description).

    ``transport(url, headers) -> (status, headers, body)`` defaults to :func:`real_transport`; ``clock()`` and ``sleep(seconds)`` default to
    ``time.perf_counter`` and ``time.sleep`` (``perf_counter``, because on Windows ``time.monotonic`` ticks only every 15.6 ms, which could turn a measured second into
    a real 0.985). ``min_interval`` can only be slower than a second. ``honour_robots=False`` is for the documented APIs of the registries, which are for programs.
    ``requests`` counts the requests made, the robots.txt ones included.

    Every failure to get a usable answer is :class:`Unreachable`; nothing is tried again, and a host that answers 401, 403 or 429 is not asked again in the run.
    """

    def __init__(
        self,
        user_agent: str,
        *,
        transport: Transport | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        min_interval: float = MIN_INTERVAL,
        honour_robots: bool = True,
        timeout: float = TIMEOUT,
        max_bytes: int = MAX_BODY_BYTES,
        product: str = PRODUCT,
    ) -> None:
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("a user agent is required")
        if not min_interval >= MIN_INTERVAL:
            raise ValueError(f"at most one request a second: the interval between requests must be {MIN_INTERVAL:g} seconds or more")
        self.user_agent = user_agent
        self.honour_robots = honour_robots
        self.max_bytes = max_bytes
        self.product = product
        self.requests = 0
        self._interval = min_interval
        self._transport: Transport = transport or real_transport(timeout)
        self._clock = clock or time.perf_counter
        self._sleep = sleep or time.sleep
        self._last_start: float | None = None
        self._robots: dict[str, Robots | str] = {}  # by origin: the rules, or the reason they could not be read
        self._refused: dict[str, str] = {}  # by origin: the answer with which the host refused a request

    def get(self, url: str, *, accept: str = "application/json") -> Reply:
        """The answer to a GET: a 200, unpacked. Anything else is :class:`Unreachable`, as is a path that robots.txt does not allow."""
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._refused:
            raise Unreachable(f"{self._refused[origin]} earlier in this run; the host is not asked again")
        if self.honour_robots:
            self._honour_robots(parts)
        status, headers, body = self._send(url, accept)
        if status in REFUSALS:
            self._refused[origin] = f"HTTP {status}"  # (a host that says no, or to slow down, is left alone for the rest of the run: the next one is a week away)
        if status != 200:
            raise Unreachable(f"HTTP {status}" + (" (a redirect is not followed)" if 300 <= status < 400 else ""))
        return Reply(status, headers, self._unpacked(body, headers))

    def get_json(self, url: str) -> Any:
        """The JSON value of a 200 answer; :class:`Unreachable` if the answer is not JSON."""
        return decode_json(self.get(url).body)

    # -- the pace and the request

    def _wait_for_turn(self) -> None:
        if self._last_start is not None:
            while (remaining := self._last_start + self._interval - self._clock()) > 0:
                self._sleep(remaining)
        self._last_start = self._clock()

    def _send(self, url: str, accept: str) -> tuple[int, dict[str, str], bytes]:
        """One request: paced, counted, and with only the headers that say who asks and what is wanted. Raises :class:`Unreachable` if there is no answer."""
        self._wait_for_turn()
        self.requests += 1
        headers = {"User-Agent": self.user_agent, "Accept": accept, "Accept-Encoding": "gzip"}
        try:
            status, reply_headers, body = self._transport(url, headers)
        except http.client.IncompleteRead:
            raise Unreachable("the answer was cut short (IncompleteRead)") from None
        except _NETWORK_ERRORS as error:
            raise Unreachable(type(error).__name__) from None
        if len(body) > self.max_bytes:
            raise Unreachable("the answer is too large")
        return status, {str(name).lower(): str(value) for name, value in (reply_headers or {}).items()}, body

    def _unpacked(self, body: bytes, headers: Mapping[str, str]) -> bytes:
        try:
            return _unpack(body, headers.get("content-encoding"), self.max_bytes)
        except _TooLarge:
            raise Unreachable("the answer is too large") from None
        except (zlib.error, ValueError):
            raise Unreachable("the answer is damaged (gzip)") from None

    # -- robots.txt

    def _honour_robots(self, parts: urllib.parse.SplitResult) -> None:
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._read_robots(origin, parts.netloc)  # (a failed read is kept too: it is not asked again in the run)
        rules = self._robots[origin]
        if isinstance(rules, str):
            raise Unreachable(rules)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if not rules.allows(target):
            raise Unreachable(f"robots.txt of {parts.netloc} does not allow {parts.path or '/'}")

    def _read_robots(self, origin: str, host: str) -> Robots | str:
        """The rules of a host, or the reason they cannot be had. A robots.txt that has moved is followed, within the site, up to five times (a wiki may serve it as a page);
        a missing file (404 and other 4xx but 429) then allows everything and a forbidden one (401, 403) nothing; an error, a move that cannot be followed or no answer
        means the host is left alone, because nobody knows what it forbids."""
        cannot = f"robots.txt of {host} could not be read"
        url = origin + "/robots.txt"
        for move in range(MAX_ROBOTS_REDIRECTS + 1):
            try:
                status, headers, body = self._send(url, "text/plain")
            except Unreachable as error:
                return f"{cannot} ({error.reason})"
            if status not in _MOVED or not headers.get("location"):
                break
            if move == MAX_ROBOTS_REDIRECTS:
                return f"{cannot} (more than {MAX_ROBOTS_REDIRECTS} redirects)"
            url = urllib.parse.urljoin(url, headers["location"])
            there = urllib.parse.urlsplit(url)
            if f"{there.scheme}://{there.netloc}" != origin:
                return f"{cannot} (it moves to another site or kind of address, which is not followed)"
        if status == 200:
            try:
                rules = parse_robots(self._unpacked(body, headers).decode("utf-8", "replace"), self.product)
            except Unreachable as error:
                return f"{cannot} ({error.reason})"
        elif status in (401, 403):
            return Robots(disallow_all=True)
        elif 400 <= status < 500 and status != 429:
            return Robots()
        else:
            return f"{cannot} (HTTP {status})"
        if rules.crawl_delay is not None:
            if rules.crawl_delay > MAX_CRAWL_DELAY:
                return f"robots.txt of {host} asks for a delay of {rules.crawl_delay:g} s between requests, longer than the {MAX_CRAWL_DELAY:g} s that a check waits"
            self._interval = max(self._interval, rules.crawl_delay)
        return rules


# ---- the dry run -----------------------------------------------------------------------------------------------------------------------------------------


class VirtualTime:
    """A clock that moves only when the code sleeps: the pace of a dry run is kept, and nobody waits for it."""

    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class ReplayTransport:
    """Recorded answers in place of the network: ``replay(url, headers) -> (status, headers, body)``.

    The entries come from ``<folder>/replay.json``, ``{"responses": [{"url", "status", "query", "headers", "body" | "file"}, ...]}``. ``url`` is an address without its
    query, ``query`` (optional) the parts of the query the request must have, ``body`` the text of the answer or ``file`` a file of the folder that holds it. A request
    gets the entry whose address is the same and whose ``query`` names the most parts that it has; one that no entry fits is a network failure (an OSError), which the
    fetcher calls unreachable. ``requests`` lists the addresses asked for.
    """

    def __init__(self, entries: Sequence[Mapping[str, Any]], folder: Path | None = None) -> None:
        self._entries = list(entries)
        self._folder = folder
        self.requests: list[str] = []

    @classmethod
    def from_directory(cls, folder: str | os.PathLike[str]) -> ReplayTransport:
        """The replay of ``<folder>/replay.json``. A file that cannot be read, or that is not what a replay is, is a ``ValueError`` with a one-line message."""
        root = Path(folder)
        try:
            document = json.loads((root / "replay.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError(f"{root / 'replay.json'} is not a file of recorded answers: it cannot be read or is not JSON") from None
        entries = document.get("responses") if isinstance(document, dict) else None
        if not isinstance(entries, list):
            raise ValueError("a replay file is an object with a list of responses")
        for number, entry in enumerate(entries, start=1):
            cls._check(entry, number, root)
        return cls(entries, root)

    @staticmethod
    def _check(entry: Any, number: int, root: Path) -> None:
        where = f"response {number} of the replay"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} is not an object")
        url = entry.get("url")
        if not isinstance(url, str) or "?" in url or urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            raise ValueError(f"{where} needs a url: an http or https address without a query (the parts of the query go in query)")
        if not isinstance(entry.get("status"), int) or isinstance(entry.get("status"), bool):
            raise ValueError(f"{where} needs a status that is a number")
        for key in ("query", "headers"):
            value = entry.get(key, {})
            if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                raise ValueError(f"{where}: {key} must be an object of text")
        if "body" in entry and not isinstance(entry["body"], str):
            raise ValueError(f"{where}: body must be text")
        if "file" in entry:
            name = entry["file"]
            target = (root / name).resolve() if isinstance(name, str) else None
            if target is None or root.resolve() not in target.parents or not target.is_file():
                raise ValueError(f"{where}: file must name a file inside the folder of the replay")

    def __call__(self, url: str, headers: Mapping[str, str]) -> tuple[int, dict[str, str], bytes]:
        self.requests.append(url)
        parts = urllib.parse.urlsplit(url)
        address = f"{parts.scheme}://{parts.netloc}{parts.path}"
        asked = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        best: Mapping[str, Any] | None = None
        for entry in self._entries:
            wanted = entry.get("query", {})
            if entry["url"] == address and all(asked.get(name) == value for name, value in wanted.items()):
                if best is None or len(wanted) > len(best.get("query", {})):
                    best = entry
        if best is None:
            raise OSError(f"no recorded answer for {address}")
        if "file" in best:
            body = (Path(self._folder or ".") / best["file"]).read_bytes()
        else:
            body = best.get("body", "").encode("utf-8")
        return best["status"], dict(best.get("headers", {})), body


# ---- time, stamps and files ------------------------------------------------------------------------------------------------------------------------------


def utc_text(when: datetime.datetime) -> str:
    """A time as UTC to the second, ``2026-10-18T10:00:03Z``. A time without a zone is a ``ValueError``: nobody knows which zone it is in."""
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("a time without a zone cannot be written as UTC")
    return when.astimezone(datetime.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text: object) -> datetime.datetime:
    """The time that ``utc_text`` wrote, or any ISO time (one without a zone is taken as UTC), as an aware UTC time. Anything else is a ``ValueError``."""
    if not isinstance(text, str):
        raise ValueError("not a time")
    try:
        when = datetime.datetime.fromisoformat(text.strip())
    except ValueError:
        raise ValueError("not an ISO time") from None
    return (when if when.tzinfo is not None else when.replace(tzinfo=datetime.timezone.utc)).astimezone(datetime.timezone.utc)


def stamp_text(when: datetime.datetime) -> str:
    """What a stamp holds: the UTC time and a line end. ``trioforge.precompute.release.scheduled_warnings`` reads the first line of it."""
    return utc_text(when) + "\n"


def write_text_atomic(path: str | os.PathLike[str], text: str) -> None:
    """Write ``text`` (UTF-8, LF line ends) to ``path`` whole or not at all: a temporary file beside it is renamed over it, and a failure keeps the old file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def report_name(name: str, when: datetime.datetime, number: int = 1) -> str:
    """The name of the report of a run: ``<name>-<UTC time>.md`` such as ``sources-check-2026-10-18T100003Z.md`` (no colons, which Windows does not allow in a name), with
    ``-2``, ``-3`` after the time for a second run in the same second."""
    stamp = utc_text(when).replace(":", "")
    return f"{name}-{stamp}.md" if number == 1 else f"{name}-{stamp}-{number}.md"


def write_new_report(directory: str | os.PathLike[str], name: str, when: datetime.datetime, text: str) -> Path:
    """Write ``text`` to ``<directory>/<name>-<UTC time>.md`` (:func:`report_name`) and return the path, **never replacing a file**: a name that is taken (by an earlier run of the
    same second, or by anything else, a broken link included) is skipped for the next number. The file itself is written whole or not at all (:func:`write_text_atomic`)."""
    folder = Path(directory)
    for number in range(1, MAX_REPORTS_A_SECOND + 1):
        target = folder / report_name(name, when, number)
        if os.path.lexists(target):
            continue
        write_text_atomic(target, text)
        return target
    raise OSError(f"{MAX_REPORTS_A_SECOND} reports of {name} in one second")


def default_folder() -> Path:
    """The folder of the stamps, the logs and the reports: ``$TRIOFORGE_CHECKS_DIR`` (an absolute path that is not in a git work tree; empty counts as unset), else
    ``~/.local/state/trioforge/checks``, on Windows too (never %LOCALAPPDATA%). It lies outside every worktree on purpose: the checks run in one checkout and a release is built in a worktree of its
    own, which reads the stamps from the same place (``trioforge.checks_dir``, whose file is loaded by its path, so that no installed copy of the package is needed and
    none can be stale). Raises :class:`ValueError` if the variable is not an absolute path or is in a git work tree."""
    path = Path(__file__).resolve().parents[1] / "pipeline" / "trioforge" / "checks_dir.py"
    spec = importlib.util.spec_from_file_location("trioforge_checks_dir_of_the_scripts", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot find the rules for the folder of the checks ({path.name})")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.checks_dir()


def write_stamp(directory: str | os.PathLike[str], name: str, when: datetime.datetime) -> Path:
    """Write ``<directory>/<name>.last-run``: the stamp of a check that ran, which the release build warns about when it is more than ten days old or missing."""
    target = Path(directory) / f"{name}{STAMP_SUFFIX}"
    write_text_atomic(target, stamp_text(when))
    return target


# ---- the log: a trace of every run, for a task that has no window ------------------------------------------------------------------------------------------


def log_line(when: datetime.datetime, outcome: str, text: str) -> str:
    """One line of a log: the UTC time, the outcome (one of :data:`OUTCOMES`) and ``text`` on a single line, cut to :data:`MAX_LOG_TEXT` characters. No line end."""
    if outcome not in OUTCOMES:
        raise ValueError(f"an outcome is one of {', '.join(OUTCOMES)}")
    flat = re.sub(r"[\x00-\x20\x7f-\x9f\u2028\u2029]+", " ", str(text)).strip()
    if len(flat) > MAX_LOG_TEXT:
        flat = flat[: MAX_LOG_TEXT - 3] + "..."
    return f"{utc_text(when)} {outcome} {flat}".rstrip()


def append_log(directory: str | os.PathLike[str], name: str, when: datetime.datetime, outcome: str, text: str, *, keep: int = LOG_LINES) -> Path | None:
    """Add one line (:func:`log_line`) to ``<directory>/<name>.log``, which keeps its last ``keep`` lines (200). A log that cannot be read or written is no failure of the
    run it is about: nothing is raised and ``None`` is returned. (A scheduled run under ``pythonw`` has no console, so this is what a refusal or a crash leaves.)"""
    target = Path(directory) / f"{name}{LOG_SUFFIX}"
    line = log_line(when, outcome, text)
    try:
        try:
            old = target.read_bytes().decode("utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            old = []
        lines = [kept for kept in old if kept.strip()] + [line]
        write_text_atomic(target, "\n".join(lines[-keep:]) + "\n")
    except OSError:
        return None
    return target


# ---- the command line of a check -----------------------------------------------------------------------------------------------------------------------------


class Refused(Exception):
    """A check that cannot run as it was asked to (bad options, no catalog, a file it cannot write): one line on standard error, exit status 2, no stamp."""


class Parser(argparse.ArgumentParser):
    """An argument parser that remembers what it objected to, so that the refusal can be logged (it still prints its usage and exits with status 2). It takes an option by its whole
    name only: argparse would take ``--dry`` for ``--dry-run`` and ``--ou`` for ``--out``, which a guard that looks for the option cannot follow."""

    problem: str | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str):  # type: ignore[override]
        self.problem = message
        super().error(message)


def path_argument(text: str) -> Path:
    """A path given on the command line (``type=`` of an option): an empty or blank one is refused, because ``Path("")`` is the working folder."""
    if not text.strip():
        raise argparse.ArgumentTypeError("must name a file or a folder, and is empty")
    return Path(text)


def same_folder(one: str | os.PathLike[str], other: str | os.PathLike[str]) -> bool:
    """Whether two paths are the same folder, however they are spelled (a dot, a trailing separator, ``..``, another case on Windows, a link)."""
    try:
        return os.path.normcase(os.path.realpath(one)) == os.path.normcase(os.path.realpath(other))
    except OSError:
        return False


def is_the_real_folder(out: str | os.PathLike[str]) -> bool:
    """Whether ``out`` is the folder of the real checks (:func:`default_folder`); False when that folder cannot be worked out."""
    try:
        return same_folder(out, default_folder())
    except ValueError:
        return False


def log_folder(args: argparse.Namespace) -> Path | None:
    """Where a run logs: ``--out`` if it was given; the folder of the checks if not; ``None`` when that folder cannot be worked out. A dry run never logs into the folder of the
    real checks (it is refused there, and leaves nothing); the scratch folder it is given with ``--out`` gets its line like any other."""
    out = getattr(args, "out", None)
    if getattr(args, "dry_run", None) is not None:
        # (a dry run leaves nothing in the folder of the real checks, not even a line of the log: it is refused there; in the scratch folder it was given it logs like any run)
        return None if out is None or is_the_real_folder(out) else Path(out)
    if out is not None:
        return Path(out)
    try:
        return default_folder()
    except ValueError:
        return None


def run_main(
    name: str,
    parser: Parser,
    argv: Sequence[str] | None,
    execute: Callable[[argparse.Namespace], str],
    *,
    now: Callable[[], datetime.datetime] | None = None,
) -> int:
    """The command line of a check, as its ``main`` runs it, with a line in the log for whatever happens.

    ``execute(args)`` does the work, prints what the check prints and returns the text of the log line (the counts and the name of the report). The exit status is 0 for a
    run that finished, 2 for one that was refused (:class:`Refused`) or failed (one line on standard error, and the traceback if ``TRIOFORGE_DEBUG`` is set) and 130 for an
    interruption. A command line that is wrong still ends the program, with the usage and status 2, and is logged first. The log is written whatever the outcome and changes
    none of them (:func:`append_log`).
    """
    clock = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
    words = list(sys.argv[1:] if argv is None else argv)
    folder: Path | None = None
    try:
        try:
            args = parser.parse_args(argv)
        except SystemExit as stop:
            if stop.code not in (0, None) and not any(str(word).startswith("--dr") for word in words):  # (a command line that names a dry run, whole or not, logs nothing in the folder of the real checks)
                try:
                    append_log(default_folder(), name, clock(), "refused", parser.problem or "the command line is not one")
                except ValueError:
                    pass
            raise
        folder = log_folder(args)
        text = execute(args)
        code, outcome = 0, "ok"
    except Refused as error:
        print(f"{name}: {error}", file=sys.stderr)
        code, outcome, text = 2, "refused", str(error)
    except KeyboardInterrupt:
        print(f"{name}: interrupted", file=sys.stderr)
        code, outcome, text = 130, "interrupted", "interrupted"
    except Exception as error:  # (a scheduled run has nobody to read a traceback: one line, and the traceback if asked for)
        if os.environ.get("TRIOFORGE_DEBUG"):
            traceback.print_exc()
        print(f"{name}: failed: {type(error).__name__}: {error}".splitlines()[0], file=sys.stderr)  # (a person who runs the check by hand sees the message)
        text = f"an unexpected fault ({type(error).__name__}); run the check by hand to see what it was"  # (the log gets the kind only: a message can hold a path of this computer)
        code, outcome = 2, "error"
    if folder is not None:
        append_log(folder, name, clock(), outcome, text)
    return code


def code_span(text: str) -> str:
    """``text`` as a Markdown code span that it cannot break out of: a fence of backticks longer than any run in the text, a space inside it where the text begins or
    ends with a backtick or a space, and no line break or other control character (each run of them becomes one space). A title from a wiki is shown this way."""
    flat = re.sub(r"[\x00-\x1f\x7f\x85\u2028\u2029]+", " ", text)
    longest = max((len(run) for run in re.findall(r"`+", flat)), default=0)
    fence = "`" * (longest + 1)
    padded = flat.strip(" ") != "" and (flat[:1] in ("`", " ") or flat[-1:] in ("`", " "))
    return f"{fence} {flat} {fence}" if padded else f"{fence}{flat}{fence}"
