"""Tests for two things the default transport of the polite client does with an answer: a body that stops before its Content-Length is a network failure that is retried
(``read`` returns what came and raises nothing when the server closes the connection early), and the body of an error answer is never read (so a 403 or a redirect is refused
as it is, and a 429 or 503 keeps its Retry-After, whatever happens to the body). The opener of the transport is replaced by a fake; nothing here touches the network.
"""

import email.message
import io
import urllib.error

import pytest

import trioforge.sources.http as http_module
from test_http import UA, FakeOpener, FakeResponse, FakeTime
from trioforge.sources.http import FetchError, PoliteClient

PAGE = "https://wiki.example.invalid/page/one"


def allow_page(url):
    return url.startswith("https://wiki.example.invalid/")


# ---- a body that stops short of its Content-Length (the default transport, with the opener replaced) ----------------------------


def fake_opener(monkeypatch, *replies):
    """Replaces the opener of the default transport: each call plays the next reply, ``(status, headers, body)``, or raises it if it is an exception."""
    calls = []
    script = list(replies)

    def function(request, timeout=None):
        calls.append(request.full_url)
        item = script.pop(0)
        if isinstance(item, BaseException):
            raise item
        status, headers, body = item
        return FakeResponse(status, headers, body)

    monkeypatch.setattr(http_module, "_OPENER", FakeOpener(function))
    return calls


def client_over_the_default_transport():
    fake_time = FakeTime()
    return PoliteClient(UA, clock=fake_time.clock, sleep=fake_time.sleep, honour_robots=False), fake_time


def test_a_body_shorter_than_its_content_length_is_retried_not_returned(monkeypatch):
    page = b"<html>" + b"x" * 100 + b"</html>"
    calls = fake_opener(monkeypatch, (200, {"Content-Length": str(len(page))}, page[:40]), (200, {"Content-Length": str(len(page))}, page))
    client, fake_time = client_over_the_default_transport()
    assert client.get_text(PAGE, allow_page) == page.decode()
    assert len(calls) == 2 and fake_time.sleeps == [2]  # (a failure of the network: the first back off)


def test_a_body_that_is_always_cut_short_ends_in_a_fetch_error_naming_the_failure(monkeypatch):
    fake_opener(monkeypatch, *[(200, {"Content-Length": "100"}, b"short")] * 6)
    client, _ = client_over_the_default_transport()
    with pytest.raises(FetchError, match="IncompleteRead"):
        client.get_text(PAGE, allow_page)


def test_a_complete_body_a_chunked_one_and_one_with_no_length_are_returned_as_they_are(monkeypatch):
    page = b"<html>fine</html>"
    for headers in ({"Content-Length": str(len(page))}, {"Transfer-Encoding": "chunked"}, {}):
        fake_opener(monkeypatch, (200, headers, page))
        client, _ = client_over_the_default_transport()
        assert client.get_text(PAGE, allow_page) == page.decode()


def test_a_json_body_cut_short_is_retried_too(monkeypatch):
    body = b'{"query": {"pages": []}}'
    fake_opener(monkeypatch, (200, {"Content-Length": str(len(body))}, body[:10]), (200, {"Content-Length": str(len(body))}, body))
    client, _ = client_over_the_default_transport()
    assert client.get_json({"action": "query"}) == {"query": {"pages": []}}


# ---- the body of an error is never read ------------------------------------------------------------------------------------------------


class BrokenBody(io.BytesIO):
    """The body of an error reply whose connection fails when it is read."""

    def read(self, size=-1):
        raise ConnectionResetError("reset while reading the body of the error")


def http_error(status, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(PAGE, status, "reason", headers, BrokenBody(b"never read"))


@pytest.mark.parametrize("status", [403, 404, 410])
def test_an_error_reply_whose_body_cannot_be_read_is_refused_at_once(monkeypatch, status):
    calls = fake_opener(monkeypatch, http_error(status))
    client, fake_time = client_over_the_default_transport()
    with pytest.raises(FetchError) as caught:
        client.get_text(PAGE, allow_page)
    assert caught.value.status == status and len(calls) == 1 and fake_time.sleeps == []  # (it was six tries with 2 to 32 s of back off)


def test_a_redirect_whose_body_cannot_be_read_is_refused_at_once(monkeypatch):
    calls = fake_opener(monkeypatch, http_error(302))
    client, fake_time = client_over_the_default_transport()
    with pytest.raises(FetchError, match="redirect refused") as caught:
        client.get_text(PAGE, allow_page)
    assert caught.value.status == 302 and len(calls) == 1 and fake_time.sleeps == []


def test_a_429_whose_body_cannot_be_read_keeps_its_retry_after(monkeypatch):
    calls = fake_opener(monkeypatch, http_error(429, "3600"))
    client, fake_time = client_over_the_default_transport()
    with pytest.raises(FetchError, match="server asked to wait too long") as caught:
        client.get_text(PAGE, allow_page)
    assert caught.value.status == 429 and len(calls) == 1 and fake_time.sleeps == []
    calls = fake_opener(monkeypatch, http_error(429, "30"), (200, {}, b"<html>fine</html>"))
    client, fake_time = client_over_the_default_transport()
    assert client.get_text(PAGE, allow_page) == "<html>fine</html>"
    assert fake_time.sleeps == [30]  # (and it is not asked again earlier than it said)


def test_an_error_reply_is_handed_on_with_its_headers_and_no_body(monkeypatch):
    fake_opener(monkeypatch, http_error(503, "9"))
    status, headers, body = http_module._urllib_transport(PAGE, {"User-Agent": UA}, timeout=5.0)
    assert (status, headers.get("Retry-After"), body) == (503, "9", b"")
