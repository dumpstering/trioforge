"""A polite HTTP client for the eqlwiki API (and, through :meth:`PoliteClient.get_text`, for the pages another site allows).

The wiki is a volunteer-run site, so the client is built to be a good guest:

* one request at a time, and never two request *starts* less than ``min_interval`` seconds
  apart (default 1.0), retries included;
* ``maxlag=5`` on every request, so the wiki can tell us to wait when its database is behind;
* ``Retry-After`` is honoured exactly (a number of seconds or an HTTP date; default 5 s when
  the header is missing or unreadable), for HTTP 429 and 503 and for an API ``maxlag`` error. It
  is never shortened, because coming back early is what gets a client blocked; a wait of more
  than 600 s (ten minutes) is not taken: the run stops with a :class:`FetchError` ("server asked
  to wait too long") and the person running it decides when to start again;
* a network failure, a timeout, a server error (5xx) or an unreadable body backs off
  2, 4, 8, 16, 32 seconds, and a request is tried at most ``max_retries`` + 1 times;
* a request that can never succeed (any other 4xx, an API error other than ``maxlag``, a body
  over the size limit, a redirect) is not retried: it raises :class:`FetchError` at once.

Redirects are never followed: every request goes through one opener whose redirect handler
refuses (a 3xx reply is a :class:`FetchError`), so the client only ever talks to
``https://eqlwiki.com/api.php``, whatever a proxy or a hijacked server answers.

A gzip body may have several members (a stream of concatenated gzip files); all are unpacked, and
the size limit counts them together.

The clock, the sleep and the transport can be replaced, so the tests run without a network and
without waiting::

    client = PoliteClient("TrioForge-extractor/0.1 (...)")
    data = client.get_json({"action": "query", "titles": "Zorblax Ring"})

:meth:`PoliteClient.get_json` only ever requests ``https://eqlwiki.com/api.php``. :meth:`PoliteClient.get_text` asks one page of
text, and only an address that the caller's ``allow`` function accepts (``trioforge.sources.eqlegendstools`` allows its zone and
item pages and nothing else); it is paced, retried and refused exactly as ``get_json`` is.
"""

from __future__ import annotations

import http.client
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import partial
from typing import Any

__all__ = ["API_URL", "FetchError", "PoliteClient"]

API_URL = "https://eqlwiki.com/api.php"

# Sent with every request; the caller's parameters cannot override them.
FIXED_PARAMS = {"format": "json", "formatversion": 2, "maxlag": 5}

DEFAULT_RETRY_AFTER = 5.0  # seconds, when the wiki gives no usable Retry-After
MAX_RETRY_AFTER = 600.0  # seconds: a longer ask stops the run (never a shorter wait than asked)
BACKOFF_BASE = 2.0  # network and server failures wait 2, 4, 8, 16, 32 s
# A response, packed or unpacked, larger than this is refused. Real batches of 50 item pages
# are well under a megabyte; the limit only stops a broken or hostile server from filling memory.
MAX_BODY_BYTES = 64 * 1024 * 1024
_GZIP_MAGIC = b"\x1f\x8b"

# What a transport can raise for "the network failed": URLError, timeouts and resets are all
# OSErrors; a response cut short is an http.client error.
_NETWORK_ERRORS = (OSError, http.client.HTTPException)

Transport = Callable[[str, Mapping[str, str]], tuple[int, Mapping[str, str], bytes]]


class FetchError(Exception):
    """A request failed for good.

    ``url`` is the request, ``status`` the last HTTP status seen (None when the network failed
    before any reply), and ``detail`` a short reason without any page text.
    """

    def __init__(self, url: str, status: int | None = None, detail: str | None = None) -> None:
        self.url = url
        self.status = status
        self.detail = detail
        reason = f"last status {status}" if status is not None else "no reply"
        if detail:
            reason += f", {detail}"
        super().__init__(f"request failed ({reason}): {url}")


class _TooLarge(Exception):
    """The response is over MAX_BODY_BYTES (packed or unpacked)."""


class _WaitTooLong(Exception):
    """The wiki asked for a wait of more than MAX_RETRY_AFTER seconds."""


class _Retry:
    """The outcome of one try that is worth another: how long to wait, or None to back off."""

    def __init__(self, status: int | None, detail: str, wait: float | None = None) -> None:
        self.status = status
        self.detail = detail
        self.wait = wait


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect handler that follows nothing: urllib then raises ``HTTPError`` with the 3xx status."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_opener(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
    """An opener like urllib's default one, but with :class:`_NoRedirect` in place of its redirect handler."""
    return urllib.request.build_opener(_NoRedirect, *handlers)


_OPENER = _build_opener()


def _urllib_transport(url: str, headers: Mapping[str, str], *, timeout: float):
    """GET ``url`` with urllib, through the opener that refuses redirects. An HTTP error status is a reply."""
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as error:
        try:
            body = error.read(MAX_BODY_BYTES + 1) if error.fp is not None else b""
        finally:
            error.close()
        return error.code, dict(error.headers.items()) if error.headers else {}, body


def _retry_after(value: str | None) -> float:
    """Seconds to wait for a Retry-After value: whole or fractional seconds, or an HTTP date.

    The wait is exact. A value that is missing or unreadable gives DEFAULT_RETRY_AFTER, and a date already
    past gives 0. Raises :class:`_WaitTooLong` for more than MAX_RETRY_AFTER seconds.
    """
    if value is None:
        return DEFAULT_RETRY_AFTER
    text = str(value).strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            moment = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return DEFAULT_RETRY_AFTER
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        seconds = max((moment - datetime.now(timezone.utc)).total_seconds(), 0.0)  # a date already past: no extra wait
    else:
        if not math.isfinite(seconds) or seconds < 0:
            return DEFAULT_RETRY_AFTER
    if seconds > MAX_RETRY_AFTER:
        raise _WaitTooLong
    return seconds


def _wait_asked(header: str | None, url: str, status: int | None) -> float:
    """:func:`_retry_after`, with a wait that is too long turned into the :class:`FetchError` that stops the run."""
    try:
        return _retry_after(header)
    except _WaitTooLong:
        raise FetchError(url, status, "server asked to wait too long") from None


def _gunzip(body: bytes) -> bytes:
    """Every member of a gzip stream, unpacked together (at most MAX_BODY_BYTES in all).

    A stream may be several gzip files one after the other; the zero bytes a gzip file may be padded with
    are ignored. Anything else after the last member, or a member cut short, is a ValueError.
    """
    parts = []
    total = 0
    while body:
        inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
        part = inflater.decompress(body, MAX_BODY_BYTES + 1 - total)  # a limit of 0 would mean "no limit"
        total += len(part)
        if total > MAX_BODY_BYTES:
            raise _TooLarge
        if not inflater.eof:
            raise ValueError("gzip stream is cut short")
        parts.append(part)
        body = inflater.unused_data.lstrip(b"\x00")
        if body and body[:2] != _GZIP_MAGIC:
            raise ValueError("unexpected bytes after the gzip stream")
    return b"".join(parts)


def _decode(body: bytes) -> Any:
    """The JSON value in a response body, gunzipped first when it is gzip (by its magic bytes)."""
    if len(body) > MAX_BODY_BYTES:
        raise _TooLarge
    if body[:2] == _GZIP_MAGIC:
        body = _gunzip(body)
    return json.loads(body.decode("utf-8"))


def _decode_text(body: bytes) -> str:
    """The text in a response body, gunzipped first when it is gzip (by its magic bytes)."""
    if len(body) > MAX_BODY_BYTES:
        raise _TooLarge
    if body[:2] == _GZIP_MAGIC:
        body = _gunzip(body)
    return body.decode("utf-8")


class PoliteClient:
    """GET requests to the eqlwiki API: serial, spaced, and patient. See the module docstring.

    ``transport(url, headers) -> (status, headers, body)`` defaults to urllib; ``clock()``
    and ``sleep(seconds)`` default to ``time.perf_counter`` and ``time.sleep``. The clock is
    ``perf_counter``, not ``time.monotonic``, because on Windows ``monotonic`` ticks only every
    15.6 ms, which could turn a measured 1.000 s gap into a real 0.985 s one.
    """

    def __init__(
        self,
        user_agent: str,
        min_interval: float = 1.0,
        max_retries: int = 5,
        timeout: float = 60.0,
        transport: Transport | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("a user agent is required")
        if not min_interval >= 0:
            raise ValueError("min_interval must be zero or more")
        if max_retries < 0:
            raise ValueError("max_retries must be zero or more")
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self._transport: Transport = transport or partial(_urllib_transport, timeout=timeout)
        self._clock = clock or time.perf_counter
        self._sleep = sleep or time.sleep
        self._last_start: float | None = None

    def get_json(self, params: Mapping[str, Any]) -> dict:
        """GET the API with ``params`` plus format=json, formatversion=2 and maxlag=5.

        Returns the decoded JSON object. Raises :class:`FetchError` when the request fails for
        good, or still fails after ``max_retries`` retries.
        """
        query = {**params, **FIXED_PARAMS}
        url = f"{API_URL}?{urllib.parse.urlencode(query)}"
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip"}
        return self._request(url, headers, self._try)

    def get_text(self, url: str, allow: Callable[[str], bool]) -> str:
        """GET one page of text (HTML) with the same pacing, retries and refusals as :meth:`get_json`.

        ``allow(url)`` must say yes for the address, or nothing is sent and a :class:`FetchError` is raised: the
        caller owns the list of hosts and paths it may ask (there is no default, so the client cannot be pointed
        anywhere by accident). The reply is gunzipped when it is gzip and read as UTF-8; a body that cannot be read
        is retried like a damaged JSON body.
        """
        if not allow(url):
            raise FetchError(url, None, "address not allowed")
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip", "Accept": "text/html"}
        return self._request(url, headers, self._try_text)

    def _request(self, url: str, headers: Mapping[str, str], attempt: Callable[[str, Mapping[str, str]], Any]) -> Any:
        """Try ``attempt(url, headers)`` until it gives a value (not a :class:`_Retry`), waiting between tries as the module says."""
        last: _Retry | None = None
        for number in range(self.max_retries + 1):
            self._wait_for_turn()
            outcome = attempt(url, headers)
            if not isinstance(outcome, _Retry):
                return outcome
            last = outcome
            if number < self.max_retries:  # no point waiting after the last failure
                wait = outcome.wait if outcome.wait is not None else BACKOFF_BASE * 2**number
                if wait > 0:
                    self._sleep(wait)
        assert last is not None
        raise FetchError(url, last.status, last.detail)

    def _wait_for_turn(self) -> None:
        """Sleep until ``min_interval`` has passed since the last request started, then start."""
        if self._last_start is not None:
            while (remaining := self._last_start + self.min_interval - self._clock()) > 0:
                self._sleep(remaining)
        self._last_start = self._clock()

    def _answer(self, url: str, headers: Mapping[str, str]) -> tuple[int, dict[str, Any], bytes] | _Retry:
        """One request, up to the checks every reply gets: ``(status, lowered headers, body)`` of a 200, or a _Retry, or FetchError if it can never work."""
        try:
            status, reply_headers, body = self._transport(url, headers)
        except _NETWORK_ERRORS as error:
            return _Retry(None, type(error).__name__)
        lowered = {str(name).lower(): value for name, value in (reply_headers or {}).items()}
        if status in (429, 503):
            return _Retry(status, "busy", _wait_asked(lowered.get("retry-after"), url, status))
        if status >= 500:
            return _Retry(status, "server error")
        if 300 <= status < 400:
            raise FetchError(url, status, "redirect refused")
        if status != 200:
            raise FetchError(url, status, "unexpected status")
        return status, lowered, body

    def _try(self, url: str, headers: Mapping[str, str]) -> dict | _Retry:
        """One request: the decoded object, or a _Retry, or FetchError if it can never work."""
        answer = self._answer(url, headers)
        if isinstance(answer, _Retry):
            return answer
        status, lowered, body = answer
        try:
            data = _decode(body)
        except _TooLarge:
            raise FetchError(url, status, "response too large") from None
        except (ValueError, RecursionError, zlib.error):  # not JSON, not UTF-8, not gzip
            return _Retry(status, "unreadable body")
        if not isinstance(data, dict):
            raise FetchError(url, status, "response is not a JSON object")
        if "error" in data:
            error = data["error"]
            code = error.get("code") if isinstance(error, dict) else None
            if code == "maxlag":
                return _Retry(status, "maxlag", _wait_asked(lowered.get("retry-after"), url, status))
            raise FetchError(url, status, f"api error {code}" if isinstance(code, str) else "api error")
        return data

    def _try_text(self, url: str, headers: Mapping[str, str]) -> str | _Retry:
        """One request for a page of text: the text, or a _Retry, or FetchError if it can never work."""
        answer = self._answer(url, headers)
        if isinstance(answer, _Retry):
            return answer
        status, _lowered, body = answer
        try:
            return _decode_text(body)
        except _TooLarge:
            raise FetchError(url, status, "response too large") from None
        except (ValueError, zlib.error):  # not UTF-8, not gzip
            return _Retry(status, "unreadable body")
