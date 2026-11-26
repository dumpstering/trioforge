"""Tests for the polite HTTP client. Nothing here touches the network.

A fake transport, clock and sleep stand in for urllib and the wall clock. The fake clock moves
only when the client sleeps or the fake transport 'takes time', so every wait is exact.
"""

import email.message
import gzip
import io
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

import trioforge.sources.http as http_module
from trioforge.sources.http import API_URL, FetchError, PoliteClient

# Written out here on purpose, so these tests do not trust the constant they check.
UA = "TrioForge-extractor/0.1 (non-commercial fan project; 1 request/s)"
OK = {"query": {"pages": []}}


class FakeTime:
    """A clock that moves only when the client sleeps or a request takes time."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeTransport:
    """Plays back a script of replies; an exception in the script is raised instead."""

    def __init__(self, fake_time, replies, latency=0.0):
        self.time = fake_time
        self.replies = list(replies)
        self.latency = latency
        self.calls = []  # (start time, url, headers)

    def __call__(self, url, headers):
        self.calls.append((self.time.now, url, dict(headers)))
        self.time.now += self.latency
        assert self.replies, "the client made a request the test did not expect: " + url
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    @property
    def starts(self):
        return [call[0] for call in self.calls]


def reply(obj=OK, *, status=200, headers=None, body=None, gz=False):
    raw = body if body is not None else json.dumps(obj).encode("utf-8")
    if gz:
        raw = gzip.compress(raw)
    return (status, dict(headers or {}), raw)


def make_client(replies, *, latency=0.0, **kwargs):
    fake_time = FakeTime()
    transport = FakeTransport(fake_time, replies, latency)
    client = PoliteClient(
        UA,
        transport=transport,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        **{"honour_robots": False, **kwargs},
    )
    return client, transport, fake_time


def query_of(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


# ---- (a) pacing ---------------------------------------------------------------------------


def test_three_requests_start_at_least_one_second_apart():
    client, transport, _ = make_client([reply(), reply(), reply()])
    for _ in range(3):
        client.get_json({"action": "query"})
    assert transport.starts == [0.0, 1.0, 2.0]


def test_interval_is_measured_between_starts_not_ends():
    client, transport, fake_time = make_client([reply(), reply(), reply()], latency=0.4)
    for _ in range(3):
        client.get_json({"action": "query"})
    assert transport.starts == pytest.approx([0.0, 1.0, 2.0])
    assert fake_time.sleeps == pytest.approx([0.6, 0.6])


def test_a_slow_response_needs_no_extra_wait():
    client, transport, fake_time = make_client([reply(), reply()], latency=1.5)
    client.get_json({"action": "query"})
    client.get_json({"action": "query"})
    assert transport.starts == [0.0, 1.5]
    assert fake_time.sleeps == []


def test_min_interval_is_configurable():
    client, transport, _ = make_client([reply(), reply(), reply()], min_interval=2.5)
    for _ in range(3):
        client.get_json({"action": "query"})
    assert transport.starts == [0.0, 2.5, 5.0]


def test_the_default_interval_is_one_second():
    client, transport, _ = make_client([reply(), reply()])
    client.get_json({"action": "query"})
    client.get_json({"action": "query"})
    assert transport.starts[1] - transport.starts[0] == 1.0


def test_retries_obey_the_interval_too():
    # A server that says "retry after 0 seconds" must still be asked no faster than the interval.
    client, transport, _ = make_client([reply(status=429, headers={"Retry-After": "0"}), reply()])
    client.get_json({"action": "query"})
    assert transport.starts == [0.0, 1.0]


# ---- (b) Retry-After ------------------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 503])
def test_busy_statuses_wait_retry_after_then_succeed(status):
    client, transport, fake_time = make_client(
        [reply(status=status, headers={"Retry-After": "3"}), reply({"ok": 1})]
    )
    assert client.get_json({"action": "query"}) == {"ok": 1}
    assert fake_time.sleeps == [3]
    assert transport.starts == [0.0, 3.0]


def test_retry_after_header_name_is_case_insensitive():
    client, _, fake_time = make_client([reply(status=429, headers={"retry-after": "4"}), reply()])
    client.get_json({"action": "query"})
    assert fake_time.sleeps == [4]


@pytest.mark.parametrize("value", ["1", "3", "119", "120", "121", "300", "599.5", "600"])
def test_a_retry_after_up_to_600_seconds_is_waited_exactly(value):
    # never a shorter wait than the wiki asked for: coming back early is what gets a client blocked
    client, transport, fake_time = make_client([reply(status=429, headers={"Retry-After": value}), reply({"ok": 1})])
    assert client.get_json({"action": "query"}) == {"ok": 1}
    assert fake_time.sleeps == [float(value)]
    assert transport.starts == [0.0, float(value)]


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("value", ["600.5", "601", "9999", "1e9"])
def test_a_retry_after_over_600_seconds_aborts_the_run_instead_of_retrying_early(status, value):
    client, transport, fake_time = make_client([reply(status=status, headers={"Retry-After": value}), reply({"ok": 1})])
    with pytest.raises(FetchError) as caught:
        client.get_json({"action": "query"})
    assert "server asked to wait too long" in str(caught.value)
    assert caught.value.status == status and caught.value.detail == "server asked to wait too long"
    assert len(transport.calls) == 1 and fake_time.sleeps == []  # no retry, no early comeback


def test_a_maxlag_error_that_asks_for_over_600_seconds_aborts_too():
    client, transport, fake_time = make_client([reply(MAXLAG, headers={"Retry-After": "9999"}), reply({"ok": 1})])
    with pytest.raises(FetchError, match="server asked to wait too long"):
        client.get_json({"action": "query"})
    assert len(transport.calls) == 1 and fake_time.sleeps == []


@pytest.mark.parametrize("value", [None, "", "soon", "-3", "nan", "inf"])
def test_retry_after_defaults_to_5_when_missing_or_unreadable(value):
    headers = {} if value is None else {"Retry-After": value}
    client, _, fake_time = make_client([reply(status=429, headers=headers), reply()])
    client.get_json({"action": "query"})
    assert fake_time.sleeps == [5]


def test_retry_after_may_be_an_http_date():
    soon = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=300), usegmt=True)
    past = format_datetime(datetime.now(timezone.utc) - timedelta(days=3650), usegmt=True)
    client, _, fake_time = make_client(
        [
            reply(status=429, headers={"Retry-After": soon}),  # five minutes ahead: waited out (to the second)
            reply(status=429, headers={"Retry-After": past}),  # already over: only the interval
            reply(),
        ]
    )
    client.get_json({"action": "query"})
    assert 295 <= fake_time.sleeps[0] <= 300  # an HTTP date has whole seconds, and a little real time passed
    assert all(wait <= 1.0 for wait in fake_time.sleeps[1:])  # no Retry-After wait for a past date


def test_a_retry_after_date_over_600_seconds_ahead_aborts_the_run():
    far = format_datetime(datetime.now(timezone.utc) + timedelta(days=3650), usegmt=True)
    client, transport, fake_time = make_client([reply(status=503, headers={"Retry-After": far}), reply()])
    with pytest.raises(FetchError, match="server asked to wait too long"):
        client.get_json({"action": "query"})
    assert len(transport.calls) == 1 and fake_time.sleeps == []


def test_429_six_times_raises_with_the_last_status():
    client, transport, fake_time = make_client([reply(status=429)] * 6)
    with pytest.raises(FetchError) as caught:
        client.get_json({"action": "query"})
    assert caught.value.status == 429
    assert caught.value.url.startswith(API_URL)
    assert len(transport.calls) == 6  # the first try plus five retries
    assert fake_time.sleeps == [5] * 5  # nothing wasted after the last failure


# ---- (c) maxlag -----------------------------------------------------------------------------

MAXLAG = {"error": {"code": "maxlag", "info": "Waiting for a database server: 6 seconds lagged."}}


def test_maxlag_error_waits_and_retries():
    client, transport, fake_time = make_client(
        [reply(MAXLAG, headers={"Retry-After": "7"}), reply({"ok": 1})]
    )
    assert client.get_json({"action": "query"}) == {"ok": 1}
    assert fake_time.sleeps == [7]
    assert len(transport.calls) == 2


def test_maxlag_without_retry_after_waits_5_seconds():
    client, _, fake_time = make_client([reply(MAXLAG), reply()])
    client.get_json({"action": "query"})
    assert fake_time.sleeps == [5]


def test_maxlag_forever_gives_up():
    client, transport, _ = make_client([reply(MAXLAG)] * 6)
    with pytest.raises(FetchError) as caught:
        client.get_json({"action": "query"})
    assert caught.value.status == 200
    assert len(transport.calls) == 6


# ---- (d) transport failures -----------------------------------------------------------------


def test_url_error_six_times_raises_fetch_error():
    failure = urllib.error.URLError("connection refused")
    client, transport, fake_time = make_client([failure] * 6)
    with pytest.raises(FetchError) as caught:
        client.get_json({"action": "query"})
    assert len(transport.calls) == 6
    assert fake_time.sleeps == [2, 4, 8, 16, 32]
    assert caught.value.url.startswith(API_URL + "?")
    assert caught.value.status is None


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError("dns"),
        TimeoutError("timed out"),
        socket.timeout("timed out"),
        ConnectionResetError("reset"),
    ],
)
def test_one_transport_failure_backs_off_2_seconds_then_succeeds(failure):
    client, _, fake_time = make_client([failure, reply({"ok": 1})])
    assert client.get_json({"action": "query"}) == {"ok": 1}
    assert fake_time.sleeps == [2]


def test_max_retries_is_configurable():
    client, transport, fake_time = make_client([urllib.error.URLError("x")] * 3, max_retries=1)
    with pytest.raises(FetchError):
        client.get_json({"action": "query"})
    assert len(transport.calls) == 2
    assert fake_time.sleeps == [2]


def test_max_retries_zero_means_a_single_try():
    client, transport, fake_time = make_client([reply(status=503)], max_retries=0)
    with pytest.raises(FetchError):
        client.get_json({"action": "query"})
    assert len(transport.calls) == 1
    assert fake_time.sleeps == []


def test_the_backoff_restarts_for_each_request():
    failure = urllib.error.URLError("x")
    client, _, fake_time = make_client([failure, reply(), failure, reply()])
    client.get_json({"action": "query"})
    client.get_json({"action": "query"})
    # 2 s after the first failure; 1 s between the two requests; 2 s again, not 4, after the next
    assert fake_time.sleeps == [2, 1, 2]


@pytest.mark.parametrize("status", [400, 403, 404])
def test_client_errors_are_not_retried(status):
    client, transport, fake_time = make_client([reply(status=status)])
    with pytest.raises(FetchError) as caught:
        client.get_json({"action": "query"})
    assert caught.value.status == status
    assert len(transport.calls) == 1
    assert fake_time.sleeps == []


@pytest.mark.parametrize("status", [500, 502, 504])
def test_server_errors_back_off_and_retry(status):
    client, _, fake_time = make_client([reply(status=status), reply({"ok": 1})])
    assert client.get_json({"action": "query"}) == {"ok": 1}
    assert fake_time.sleeps == [2]


def test_an_api_error_other_than_maxlag_is_not_retried():
    error = {"error": {"code": "badvalue", "info": "bad cmtitle"}}
    client, transport, _ = make_client([reply(error)])
    with pytest.raises(FetchError) as caught:
        client.get_json({"action": "query"})
    assert caught.value.status == 200
    assert "badvalue" in str(caught.value)
    assert len(transport.calls) == 1


def test_a_response_that_is_not_a_json_object_is_refused():
    client, transport, _ = make_client([reply(["not", "an", "object"])])
    with pytest.raises(FetchError):
        client.get_json({"action": "query"})
    assert len(transport.calls) == 1


# ---- (e) request shape ----------------------------------------------------------------------


def test_the_user_agent_header_is_the_constant():
    client, transport, _ = make_client([reply()])
    client.get_json({"action": "query"})
    headers = transport.calls[0][2]
    assert headers["User-Agent"] == UA
    assert headers["Accept-Encoding"] == "gzip"
    assert set(headers) == {"User-Agent", "Accept-Encoding"}


def test_the_request_goes_to_api_php_with_the_fixed_parameters():
    client, transport, _ = make_client([reply()])
    client.get_json({"action": "query", "titles": "Zorblax's Ring|Other"})
    url = transport.calls[0][1]
    assert url.startswith("https://eqlwiki.com/api.php?")
    assert query_of(url) == {
        "action": "query",
        "titles": "Zorblax's Ring|Other",
        "format": "json",
        "formatversion": "2",
        "maxlag": "5",
    }


def test_the_caller_cannot_override_the_fixed_parameters():
    client, transport, _ = make_client([reply()])
    client.get_json({"action": "query", "format": "xml", "formatversion": 1, "maxlag": 99})
    query = query_of(transport.calls[0][1])
    assert (query["format"], query["formatversion"], query["maxlag"]) == ("json", "2", "5")


def test_the_same_headers_are_sent_on_every_retry():
    client, transport, _ = make_client([reply(status=429), reply()])
    client.get_json({"action": "query"})
    assert transport.calls[0][2] == transport.calls[1][2]
    assert transport.calls[0][1] == transport.calls[1][1]


# ---- (f) bodies -----------------------------------------------------------------------------


def test_a_gzip_body_decodes():
    client, _, _ = make_client([reply({"a": 1}, gz=True, headers={"Content-Encoding": "gzip"})])
    assert client.get_json({"action": "query"}) == {"a": 1}


def test_a_gzip_body_decodes_even_without_the_header():
    client, _, _ = make_client([reply({"a": 1}, gz=True)])
    assert client.get_json({"action": "query"}) == {"a": 1}


def test_a_gzip_body_with_several_members_decodes_completely():
    body = gzip.compress(b'{"a": 1, ') + gzip.compress(b'"b": [2, ') + gzip.compress(b"3]}")
    client, transport, _ = make_client([(200, {"Content-Encoding": "gzip"}, body)])
    assert client.get_json({"action": "query"}) == {"a": 1, "b": [2, 3]}
    assert len(transport.calls) == 1


def test_zero_padding_after_the_last_gzip_member_is_ignored():
    body = gzip.compress(b'{"a": 1}') + b"\x00" * 7
    client, _, _ = make_client([(200, {}, body)])
    assert client.get_json({"action": "query"}) == {"a": 1}


def test_other_bytes_after_the_last_gzip_member_make_the_body_unreadable_and_it_is_retried():
    client, transport, fake_time = make_client([(200, {}, gzip.compress(b'{"a": 1}') + b"junk"), reply({"a": 2})])
    assert client.get_json({"action": "query"}) == {"a": 2}
    assert len(transport.calls) == 2 and fake_time.sleeps == [2]


def test_a_gzip_body_cut_short_in_its_second_member_is_retried():
    cut = gzip.compress(b'{"a": 1, ') + gzip.compress(b'"b": 2}')[:-6]
    client, transport, _ = make_client([(200, {}, cut), reply({"a": 3})])
    assert client.get_json({"action": "query"}) == {"a": 3}
    assert len(transport.calls) == 2


def test_the_size_limit_counts_every_gzip_member_together(monkeypatch):
    monkeypatch.setattr(http_module, "MAX_BODY_BYTES", 1000)
    members = gzip.compress(b"0" * 600) * 3  # each member is small and inflates to 600 bytes; together 1,800
    assert len(members) < 1000
    client, transport, _ = make_client([(200, {}, members)])
    with pytest.raises(FetchError, match="too large"):
        client.get_json({"action": "query"})
    assert len(transport.calls) == 1


def test_a_plain_body_decodes():
    client, _, _ = make_client([reply({"café": "Ünïcode"})])
    assert client.get_json({"action": "query"}) == {"café": "Ünïcode"}


def test_a_corrupt_gzip_body_is_retried():
    bad = (200, {}, gzip.compress(b'{"a": 1}')[:-6])  # cut off inside the stream
    client, transport, fake_time = make_client([bad, reply({"a": 1})])
    assert client.get_json({"action": "query"}) == {"a": 1}
    assert fake_time.sleeps == [2]
    assert len(transport.calls) == 2


@pytest.mark.parametrize("body", [b"<html>502 Bad Gateway</html>", b"", b'{"a": '])
def test_a_body_that_is_not_json_is_retried(body):
    client, _, fake_time = make_client([reply(body=body), reply({"a": 1})])
    assert client.get_json({"action": "query"}) == {"a": 1}
    assert fake_time.sleeps == [2]


def test_an_oversized_body_is_refused_not_retried(monkeypatch):
    monkeypatch.setattr(http_module, "MAX_BODY_BYTES", 100)
    client, transport, _ = make_client([reply(body=b"x" * 101)])
    with pytest.raises(FetchError):
        client.get_json({"action": "query"})
    assert len(transport.calls) == 1


def test_a_gzip_bomb_is_refused_not_retried(monkeypatch):
    monkeypatch.setattr(http_module, "MAX_BODY_BYTES", 1000)
    bomb = gzip.compress(b"0" * 100_000)
    assert len(bomb) < 1000  # small on the wire, large when unpacked
    client, transport, _ = make_client([(200, {}, bomb)])
    with pytest.raises(FetchError):
        client.get_json({"action": "query"})
    assert len(transport.calls) == 1


# ---- the default transport (urllib), with the opener replaced --------------------------------
# The transport sends every request through one opener that refuses redirects (see the tests below), so
# these tests put a fake opener in its place instead of replacing urllib.request.urlopen.


class FakeOpener:
    """Stands in for http_module._OPENER: open(request, timeout=...) calls the test's function."""

    def __init__(self, function):
        self.function = function

    def open(self, request, timeout=None):
        return self.function(request, timeout=timeout)



class FakeResponse:
    def __init__(self, status, headers, body):
        self.status = status
        message = email.message.Message()
        for name, value in headers.items():
            message[name] = value
        self.headers = message
        self._body = io.BytesIO(body)

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_default_transport_returns_status_headers_and_body(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["headers"] = {name.lower(): value for name, value in request.header_items()}
        seen["method"] = request.get_method()
        seen["timeout"] = timeout
        return FakeResponse(200, {"Content-Encoding": "gzip"}, b'{"ok": 1}')

    monkeypatch.setattr(http_module, "_OPENER", FakeOpener(fake_urlopen))
    client = PoliteClient(UA, timeout=12.5, clock=FakeTime().clock, sleep=lambda s: None, honour_robots=False)
    assert client.get_json({"action": "query"}) == {"ok": 1}
    assert seen["url"].startswith(API_URL + "?")
    assert seen["headers"]["user-agent"] == UA
    assert seen["headers"]["accept-encoding"] == "gzip"
    assert seen["method"] == "GET"
    assert seen["timeout"] == 12.5


def test_default_transport_turns_http_errors_into_statuses(monkeypatch):
    headers = email.message.Message()
    headers["Retry-After"] = "3"
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", headers, io.BytesIO(b""))
        return FakeResponse(200, {}, b'{"ok": 1}')

    monkeypatch.setattr(http_module, "_OPENER", FakeOpener(fake_urlopen))
    fake_time = FakeTime()
    client = PoliteClient(UA, clock=fake_time.clock, sleep=fake_time.sleep, honour_robots=False)
    assert client.get_json({"action": "query"}) == {"ok": 1}
    assert fake_time.sleeps == [3]  # the 429 was read as a status, not as a network failure


def test_default_transport_failures_are_retried(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.URLError("no route")
        return FakeResponse(200, {}, b'{"ok": 1}')

    monkeypatch.setattr(http_module, "_OPENER", FakeOpener(fake_urlopen))
    fake_time = FakeTime()
    client = PoliteClient(UA, clock=fake_time.clock, sleep=fake_time.sleep, honour_robots=False)
    assert client.get_json({"action": "query"}) == {"ok": 1}
    assert fake_time.sleeps == [2]


# ---- redirects are refused ------------------------------------------------------------------


class OpenerReply(FakeResponse):
    """A reply with what urllib's handlers read from it (code, msg, info(), geturl())."""

    def __init__(self, status, headers, body, url):
        super().__init__(status, headers, body)
        self.code = status
        self.msg = "reason"
        self._url = url

    def info(self):
        return self.headers

    def geturl(self):
        return self._url

    def close(self):
        pass


class FakeHTTPS(urllib.request.BaseHandler):
    """Answers https requests from a script, ahead of the real HTTPS handler, and records the URLs asked for."""

    handler_order = 100

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def https_open(self, request):
        self.seen.append(request.full_url)
        status, headers, body = self.replies.pop(0)
        return OpenerReply(status, headers, body, request.full_url)


def test_the_opener_has_no_redirect_handler_that_follows():
    handlers = http_module._OPENER.handlers
    redirecting = [h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert redirecting and all(isinstance(h, http_module._NoRedirect) for h in redirecting)


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_the_redirect_handler_builds_no_new_request(code):
    handler = http_module._NoRedirect()
    request = urllib.request.Request(API_URL)
    assert handler.redirect_request(request, io.BytesIO(b""), code, "Moved", {}, "https://elsewhere.example/x") is None


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_a_redirect_is_refused_and_its_target_is_never_requested(monkeypatch, code):
    fake = FakeHTTPS((code, {"Location": "https://elsewhere.example/api.php"}, b""))
    monkeypatch.setattr(http_module, "_OPENER", http_module._build_opener(fake))
    fake_time = FakeTime()
    client = PoliteClient(UA, clock=fake_time.clock, sleep=fake_time.sleep, honour_robots=False)
    with pytest.raises(FetchError) as caught:
        client.get_json({"action": "query"})
    assert caught.value.status == code and "redirect refused" in str(caught.value)
    assert [url.split("?")[0] for url in fake.seen] == [API_URL]  # one request, to the API and nowhere else
    assert fake_time.sleeps == []  # and not retried


def test_the_opener_still_delivers_an_ordinary_reply(monkeypatch):
    fake = FakeHTTPS((200, {}, b'{"ok": 1}'))
    monkeypatch.setattr(http_module, "_OPENER", http_module._build_opener(fake))
    client = PoliteClient(UA, clock=FakeTime().clock, sleep=lambda s: None, honour_robots=False)
    assert client.get_json({"action": "query"}) == {"ok": 1}


def test_the_transport_never_uses_the_global_urlopen(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("urllib.request.urlopen follows redirects")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(http_module, "_OPENER", FakeOpener(lambda request, timeout=None: FakeResponse(200, {}, b'{"ok": 1}')))
    client = PoliteClient(UA, clock=FakeTime().clock, sleep=lambda s: None, honour_robots=False)
    assert client.get_json({"action": "query"}) == {"ok": 1}


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_status_from_any_transport_is_a_fetch_error_and_is_not_retried(status):
    client, transport, fake_time = make_client([reply(status=status, headers={"Location": "https://elsewhere.example/"})])
    with pytest.raises(FetchError, match="redirect refused") as caught:
        client.get_json({"action": "query"})
    assert caught.value.status == status
    assert len(transport.calls) == 1 and fake_time.sleeps == []


# ---- construction ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [{"user_agent": ""}, {"user_agent": UA, "min_interval": -1}, {"user_agent": UA, "max_retries": -1}],
)
def test_nonsense_settings_are_refused(kwargs):
    with pytest.raises(ValueError):
        PoliteClient(**kwargs)
