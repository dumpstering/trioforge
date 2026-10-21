"""Helpers of the tests of the scheduled checks (``scripts/sources_check.py``, ``scripts/pins_check.py`` and their shared ``scripts/checks_common.py``).

The scripts are not a package: they sit in ``scripts/`` and import each other by name, as they do when the Task Scheduler runs one of them. This module puts
that folder on the path, so a test can ``import checks_common`` and ``import sources_check``. Nothing here touches the network: a fake clock, a fake sleep and
a fake transport stand in for the wall clock and for urllib, and the fake clock moves only when the code sleeps or the fake transport "takes time", so every
wait is exact.
"""

from __future__ import annotations

import gzip
import json
import sys
import urllib.parse
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checks_common as common  # noqa: E402

CONTACT = common.DEFAULT_CONTACT  # the page that the user agent of a run points to, unless a test gives another
USER_AGENT = common.user_agent(CONTACT)


class FakeTime:
    """A clock that moves only when the code sleeps or a request takes time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeTransport:
    """Answers each request with ``handler(url, headers)``: a ``(status, headers, body)`` triple, or an exception to raise. It keeps what it was asked."""

    def __init__(self, fake_time: FakeTime, handler: Callable[[str, dict], object], latency: float = 0.0) -> None:
        self.time = fake_time
        self.handler = handler
        self.latency = latency
        self.calls: list[tuple[float, str, dict]] = []  # (start time, url, headers)

    def __call__(self, url: str, headers) -> tuple[int, dict, bytes]:
        self.calls.append((self.time.now, url, dict(headers)))
        self.time.now += self.latency
        answer = self.handler(url, dict(headers))
        if isinstance(answer, BaseException):
            raise answer
        return answer  # type: ignore[return-value]

    @property
    def starts(self) -> list[float]:
        return [call[0] for call in self.calls]

    @property
    def urls(self) -> list[str]:
        return [call[1] for call in self.calls]

    def paths(self, host: str | None = None) -> list[str]:
        """The path (and query) of each request, for one host or for all."""
        found = []
        for url in self.urls:
            parts = urllib.parse.urlsplit(url)
            if host is None or parts.netloc == host:
                found.append(parts.path + (f"?{parts.query}" if parts.query else ""))
        return found


def reply(status: int = 200, body: bytes | str | object = b"", headers: dict | None = None, *, gz: bool = False) -> tuple[int, dict, bytes]:
    """A ``(status, headers, body)`` triple. A body that is not bytes or text is written as JSON."""
    if isinstance(body, str):
        raw = body.encode("utf-8")
    elif isinstance(body, (bytes, bytearray)):
        raw = bytes(body)
    else:
        raw = json.dumps(body).encode("utf-8")
    sent = dict(headers or {})
    if gz:
        raw = gzip.compress(raw)
        sent["Content-Encoding"] = "gzip"
    return status, sent, raw


def make_fetcher(handler: Callable[[str, dict], object], *, latency: float = 0.0, contact: str = CONTACT, **kwargs):
    """``(fetcher, transport, fake_time)`` for a handler."""
    fake_time = FakeTime()
    transport = FakeTransport(fake_time, handler, latency)
    fetcher = common.Fetcher(common.user_agent(contact), transport=transport, clock=fake_time.clock, sleep=fake_time.sleep, **kwargs)
    return fetcher, transport, fake_time


def query_of(url: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
