"""The rules about asking a site for pages that the scheduled checks (``scripts/checks_common.py``) and the fetchers of the sources (``trioforge.sources.http``) share, so that
there is one reading of a robots.txt and one test for an answer that stopped short.

* :class:`Robots` and :func:`parse_robots`: what one robots.txt allows this program, by the rules of RFC 9309, and the ``Crawl-delay`` it asks for.
* :func:`check_complete`: an answer whose body stops before its ``Content-Length`` is an :class:`http.client.IncompleteRead`.

Standard library only, and no import of the package: the scripts load this file by its path (a scheduled task runs them with the project's Python and nothing else on the
path), and the package imports it by its name.
"""

from __future__ import annotations

import http.client
import math
import re
import urllib.parse
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["MAX_BODY_BYTES", "MAX_CRAWL_DELAY", "MAX_ROBOTS_BYTES", "Robots", "check_complete", "limit_robots", "parse_robots", "product_of"]

MAX_CRAWL_DELAY = 60.0  # a host that asks for more between requests than this is left alone for the run
MAX_BODY_BYTES = 64 * 1024 * 1024  # an answer over this, packed or unpacked, is refused
MAX_ROBOTS_BYTES = 512 * 1024  # a robots.txt is read up to this much and no further (RFC 9309 lets a parser cap what it reads, and asks for at least 500 KiB): the rest is cut, not refused


def product_of(user_agent: str) -> str:
    """The name robots.txt knows a program by: the first word of its user agent, without the version (``TrioForge-extractor`` of ``TrioForge-extractor/0.1 (...)``)."""
    words = re.split(r"[/\s(]", user_agent.strip(), maxsplit=1)
    return words[0] or user_agent.strip()


class Robots:
    """What one robots.txt allows this program: ``allows(target)`` for a path with its query, and the ``crawl_delay`` its group asks for (or None).

    The rules are those of RFC 9309. Of the rules of the group that applies, the one with the longest pattern that matches the start of the target decides, and
    ``Allow`` wins a tie; ``*`` in a pattern stands for any text and ``$`` at its end anchors it; no rule that matches means allowed; an empty ``Disallow`` forbids
    nothing.
    """

    def __init__(self, rules: Sequence[tuple[bool, str]] = (), crawl_delay: float | None = None, *, disallow_all: bool = False) -> None:
        self.crawl_delay = crawl_delay
        self._disallow_all = disallow_all
        self._rules = [(allow, len(pattern), _compile(pattern)) for allow, pattern in rules if pattern]

    def allows(self, target: str) -> bool:
        if self._disallow_all:
            return False
        text = urllib.parse.unquote(target)
        best, verdict = -1, True
        for allow, length, (parts, anchored) in self._rules:
            if (length > best or (length == best and allow)) and _matches(parts, anchored, text):
                best, verdict = length, allow
        return verdict


def _compile(pattern: str) -> tuple[list[str], bool]:
    """A pattern as the pieces of text between its stars, and whether a ``$`` at its end anchors it to the end of the target."""
    text = urllib.parse.unquote(pattern)
    anchored = text.endswith("$")
    return (text[:-1] if anchored else text).split("*"), anchored


def _matches(parts: Sequence[str], anchored: bool, text: str) -> bool:
    """Whether the pattern given as ``parts`` (see :func:`_compile`) matches the start of ``text`` (all of it, when anchored): the first piece at the start, each next piece at its first place after the one
    before, the last at the end when the pattern is anchored. Taking each piece where it first fits leaves the most room for the rest, so this says what a regular expression with ``.*`` for a star and ``\\Z``
    for the anchor says, which is RFC 9309's meaning, and it never goes back over a piece: the work is the length of the pattern times the length of the target at the most, where a regular expression with many
    stars took seconds. It differs from the expression it replaced (whose anchor was Python's ``$``) in one case only: ``$`` also matched before a final newline, so ``/a$`` used to block ``/a%0A`` (a target
    that unquotes to ``/a`` and a newline) and does not now: the end of the target is its very end."""
    first = parts[0]
    if len(parts) == 1:
        return text == first if anchored else text.startswith(first)
    if not text.startswith(first):
        return False
    position = len(first)
    for piece in parts[1:-1]:
        found = text.find(piece, position)
        if found < 0:
            return False
        position = found + len(piece)
    last = parts[-1]
    if not anchored:
        found = text.find(last, position)
        return found >= 0
    return text.endswith(last) and len(text) - len(last) >= position


def parse_robots(text: str, product: str) -> Robots:
    """The :class:`Robots` of a robots.txt for the program called ``product``.

    A group (one or more ``User-agent`` lines, then its rules) applies when one of its names is the program's or the front of it up to a hyphen (``trioforge`` for
    ``trioforge-checks``); the groups of that kind are the program's, and only when there are none are the groups for ``*``. Field names have no case; a byte order
    mark, CRLF line ends and ``#`` comments are read; a rule before any ``User-agent`` line belongs to nobody.
    """
    token = product.lower()
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    after_agent = False
    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.split("#", 1)[0].strip()
        field, colon, value = line.partition(":")
        if not colon:
            continue
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if current is None or not after_agent:
                current = {"agents": [], "rules": [], "delay": None}
                groups.append(current)
            current["agents"].append(value.lower())
            after_agent = True
        elif field in ("allow", "disallow", "crawl-delay"):
            after_agent = False
            if current is None:
                continue
            if field == "crawl-delay":
                try:
                    delay = float(value)
                except ValueError:
                    continue
                if math.isfinite(delay) and delay >= 0:
                    current["delay"] = delay
            else:
                current["rules"].append((field == "allow", value))
    ours = [g for g in groups if any(a == token or (a and a != "*" and token.startswith(a + "-")) for a in g["agents"])]
    chosen = ours or [g for g in groups if "*" in g["agents"]]
    delays = [g["delay"] for g in chosen if g["delay"] is not None]
    return Robots([rule for g in chosen for rule in g["rules"]], max(delays) if delays else None)


def limit_robots(body: bytes) -> bytes:
    """``body`` as it is read: all of it up to :data:`MAX_ROBOTS_BYTES`; a longer one is cut at the limit, and the partial last line goes with the cut, so that what is kept ends at a line end: only up to and
    including the last LF or CR before the limit (nothing at all when there is none). A rule cut short is a different rule: ``Allow: /public/only-this-page`` cut to ``Allow: /pu`` allows what the whole file
    blocks, and ``Crawl-delay: 30`` cut to ``Crawl-delay: 3`` is ten times faster than asked. What is past the limit is not read."""
    if len(body) <= MAX_ROBOTS_BYTES:
        return body
    cut = body[:MAX_ROBOTS_BYTES]
    return cut[: max(cut.rfind(b"\n"), cut.rfind(b"\r")) + 1]


def check_complete(status: int, headers: Mapping[str, str], body: bytes, max_body: int = MAX_BODY_BYTES) -> None:
    """Raise :class:`http.client.IncompleteRead` if ``body`` stops before the ``Content-Length`` that the answer promised.

    ``read(n)`` of an answer with a length returns what came when the server closed the connection early and raises nothing, so a robots.txt cut before its ``Disallow``
    lines would allow everything and a JSON cut in two would have another hash and be reported as changed. (An answer that is chunked is checked by ``http.client``
    itself, which raises when the last chunk does not come; an answer with no length ends where the connection does, and nothing says it is short; a 204, a 304 and a 1xx
    have no body whatever their headers say; and a body of more than ``MAX_BODY_BYTES`` was cut by us and is refused as too large.)"""
    if status in (204, 304) or 100 <= status < 200 or len(body) > max_body:
        return
    lowered = {str(name).lower(): str(value).strip() for name, value in headers.items()}
    if "transfer-encoding" in lowered or not re.fullmatch(r"[0-9]{1,15}", lowered.get("content-length", "")):
        return
    promised = int(lowered["content-length"])
    if len(body) < promised:
        raise http.client.IncompleteRead(body, promised - len(body))
