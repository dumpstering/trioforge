"""Tests for ``scripts/checks_common.py``, the pieces that the scheduled checks share: the polite fetcher (a request a second, the project's own user agent,
robots.txt), the rule that a bad answer is "unreachable" and never a change, the stamps the release build reads, and the dry-run replay.

Nothing here touches the network. A fake clock, sleep and transport stand in for the wall clock and urllib; the one test of the real transport talks to a
server on the loopback address that the test starts itself.
"""

from __future__ import annotations

import datetime
import gzip
import http.client
import http.server
import json
import re
import threading
import time
import urllib.error
import urllib.parse
from pathlib import Path

import pytest
from checks_helpers import USER_AGENT, FakeTime, make_fetcher, reply

import checks_common as common
from trioforge.precompute import release

NOW = datetime.datetime(2026, 10, 18, 12, 0, 0, tzinfo=datetime.timezone.utc)


def ok_for_all(url, headers):
    """Every robots.txt is missing and everything else is a small JSON object."""
    return reply(404) if url.endswith("/robots.txt") else reply(200, {"n": 1})


# ---- the pace: at most one request a second --------------------------------------------------------------------------------------------------------------


def test_requests_start_a_second_apart_whatever_the_host():
    fetcher, transport, _ = make_fetcher(ok_for_all, honour_robots=False)
    for url in ("https://one.invalid/a", "https://two.invalid/b", "https://one.invalid/c"):
        fetcher.get(url)
    assert transport.starts == [0.0, 1.0, 2.0]


def test_the_robots_request_is_paced_like_every_other_request():
    fetcher, transport, _ = make_fetcher(ok_for_all)
    fetcher.get("https://one.invalid/a")
    fetcher.get("https://two.invalid/b")
    assert transport.paths() == ["/robots.txt", "/a", "/robots.txt", "/b"]
    assert transport.starts == [0.0, 1.0, 2.0, 3.0]
    assert fetcher.requests == 4


def test_the_second_is_counted_from_the_start_of_a_request_not_from_its_end():
    fetcher, transport, fake_time = make_fetcher(ok_for_all, latency=0.4, honour_robots=False)
    for _ in range(3):
        fetcher.get("https://one.invalid/a")
    assert transport.starts == pytest.approx([0.0, 1.0, 2.0])
    assert fake_time.sleeps == pytest.approx([0.6, 0.6])


def test_a_slow_answer_needs_no_extra_wait():
    fetcher, transport, fake_time = make_fetcher(ok_for_all, latency=1.5, honour_robots=False)
    fetcher.get("https://one.invalid/a")
    fetcher.get("https://one.invalid/b")
    assert transport.starts == [0.0, 1.5]
    assert fake_time.sleeps == []


@pytest.mark.parametrize("interval", [0.0, 0.2, 0.999, -1.0, float("nan")])
def test_a_pace_faster_than_a_request_a_second_is_refused(interval):
    with pytest.raises(ValueError, match="second"):
        common.Fetcher(USER_AGENT, min_interval=interval)


def test_a_slower_pace_is_allowed():
    fetcher, transport, _ = make_fetcher(ok_for_all, honour_robots=False, min_interval=2.5)
    for _ in range(3):
        fetcher.get("https://one.invalid/a")
    assert transport.starts == [0.0, 2.5, 5.0]


# ---- the user agent and what else is sent ----------------------------------------------------------------------------------------------------------------


def test_the_user_agent_names_the_project_and_the_page_of_the_site_that_says_who_runs_it():
    assert common.DEFAULT_CONTACT == "https://trioforge.pages.dev/about/"  # (the repository is private until it is made public: its issues would be a 404)
    agent = common.user_agent()
    assert agent == common.user_agent(common.DEFAULT_CONTACT)
    assert agent.startswith("TrioForge-checks/") and "(+https://trioforge.pages.dev/about/;" in agent
    assert "1 request/s" in agent and "github" not in agent
    assert agent.isascii() and "\n" not in agent and len(agent) < 250


def test_the_contact_of_the_user_agent_can_be_another_page():
    assert "(+https://example.invalid/hello/;" in common.user_agent("https://example.invalid/hello/")


def test_the_request_carries_the_user_agent_and_nothing_that_identifies_a_person():
    fetcher, transport, _ = make_fetcher(ok_for_all)
    fetcher.get("https://one.invalid/a", accept="application/json")
    robots_headers, headers = (call[2] for call in transport.calls)
    assert headers == {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "gzip"}
    assert robots_headers["User-Agent"] == USER_AGENT and set(robots_headers) == {"User-Agent", "Accept", "Accept-Encoding"}


@pytest.mark.parametrize(
    "contact",
    [
        "https://trioforge.pages.dev/about/",
        "https://example.invalid/",
        "http://127.0.0.1:8799/about/",
        "https://example.invalid:8443/a/b.html?x=1&y=2",
        "https://github.com/some-account/trioforge/issues",
    ],
)
def test_a_contact_is_an_http_or_https_address_of_plain_ascii(contact):
    assert common.check_contact(contact) == contact


@pytest.mark.parametrize(
    "contact",
    [
        "",
        None,
        5,
        "trioforge.pages.dev",
        "//trioforge.pages.dev/about/",
        "ftp://example.invalid/",
        "javascript:alert(1)",
        "mailto:someone@example.invalid",
        "https:///no-host",
        "https://user:secret@example.invalid/",
        "https://example.invalid/ about",
        "https://example.invalid/\n",
        "https://example.invalid/;extra",
        "https://example.invalid/(a)",
        "https://example.invalid/<a>",
        'https://example.invalid/"a"',
        "https://exämple.invalid/",
        "https://example.invalid/" + "a" * 300,
    ],
)
def test_a_contact_that_could_break_the_header_or_is_not_an_address_is_refused(contact):
    with pytest.raises(ValueError):
        common.check_contact(contact)
    if isinstance(contact, str):
        with pytest.raises(ValueError):
            common.user_agent(contact)


# ---- robots.txt: the rules -------------------------------------------------------------------------------------------------------------------------------

ROBOTS_CASES = [
    ("", "/api.php", True),
    ("User-agent: *\nDisallow: /", "/api.php", False),
    ("User-agent: *\nDisallow:", "/api.php", True),  # an empty Disallow forbids nothing
    ("User-agent: *\nDisallow: /api.php", "/api.php?action=query", False),  # a prefix, and the query is part of what is matched
    ("User-agent: *\nDisallow: /api.php", "/index.php", True),
    ("User-agent: *\nDisallow: /\nAllow: /api.php", "/api.php?x=1", True),  # the longer rule wins ...
    ("User-agent: *\nAllow: /api.php\nDisallow: /", "/api.php?x=1", True),  # ... whatever the order
    ("User-agent: *\nAllow: /w/api\nDisallow: /w/", "/w/api.php", True),
    ("User-agent: *\nDisallow: /w/\nAllow: /w/api", "/w/index.php", False),
    ("User-agent: *\nDisallow: /*action=raw", "/index.php?title=X&action=raw", False),  # a star stands for any text
    ("User-agent: *\nDisallow: /*action=raw", "/index.php?title=X", True),
    ("User-agent: *\nDisallow: /*.json$", "/data/x.json", False),  # a dollar sign anchors the end
    ("User-agent: *\nDisallow: /*.json$", "/data/x.json?cache=1", True),
    ("User-agent: *\nDisallow: /a\nAllow: /a", "/a", True),  # as long as each other: allowing wins
    ("User-agent: trioforge-checks\nDisallow: /\n\nUser-agent: *\nAllow: /", "/x", False),  # a group for this program beats the group for all
    ("User-agent: otherbot\nDisallow: /\n\nUser-agent: *\nAllow: /", "/x", True),
    ("User-agent: otherbot\nDisallow: /", "/x", True),  # no group for this program and none for all
    ("User-agent: TrioForge\nDisallow: /x", "/x", False),  # a name that is part of the program's counts
    ("User-agent: a\nUser-agent: trioforge-checks\nDisallow: /x", "/x", False),  # several user-agent lines make one group
    ("User-agent: trioforge-checks\nDisallow: /x\n\nUser-agent: trioforge-checks\nDisallow: /y", "/y", False),  # groups of the same name are one
    ("\ufeffUser-agent: *\r\nDisallow: /x # not this\r\n", "/x", False),  # a byte order mark, CRLF line ends, a comment
    ("USER-AGENT: *\nDISALLOW: /x", "/x", False),  # the field names have no case
    ("Disallow: /x", "/x", True),  # a rule before any user-agent line belongs to nobody
    ("User-agent: *\nDisallow: /x%41", "/xA", False),  # percent-encoding is undone on both sides
    ("User-agent: *\nDisallow: /xA", "/x%41", False),
    ("User-agent: *\nSitemap: https://one.invalid/s.xml\nDisallow: /x", "/x", False),  # a line of another kind does not end a group
]


@pytest.mark.parametrize("text, target, allowed", ROBOTS_CASES)
def test_robots_rules(text, target, allowed):
    assert common.parse_robots(text).allows(target) is allowed


def test_a_crawl_delay_of_the_group_that_applies_is_read():
    assert common.parse_robots("User-agent: *\nCrawl-delay: 3\nDisallow: /x").crawl_delay == 3.0
    assert common.parse_robots("User-agent: trioforge-checks\nCrawl-delay: 7.5\n\nUser-agent: *\nCrawl-delay: 1").crawl_delay == 7.5
    assert common.parse_robots("User-agent: otherbot\nCrawl-delay: 9").crawl_delay is None
    assert common.parse_robots("User-agent: *\nCrawl-delay: soon").crawl_delay is None
    assert common.parse_robots("User-agent: *\nCrawl-delay: -4").crawl_delay is None


# ---- robots.txt: what the fetcher does with it ------------------------------------------------------------------------------------------------------------


def with_robots(text: str, status: int = 200):
    def handler(url, headers):
        return reply(status, text) if url.endswith("/robots.txt") else reply(200, {"n": 1})

    return handler


def test_a_path_that_robots_disallows_is_never_requested():
    fetcher, transport, _ = make_fetcher(with_robots("User-agent: *\nDisallow: /api.php"))
    with pytest.raises(common.Unreachable, match="robots"):
        fetcher.get("https://one.invalid/api.php?action=query")
    assert transport.paths() == ["/robots.txt"]
    assert fetcher.get("https://one.invalid/index.php").status == 200  # another path of the same host is asked for


def test_the_robots_file_of_a_host_is_read_once():
    fetcher, transport, _ = make_fetcher(with_robots("User-agent: *\nDisallow: /nope"))
    for path in ("/a", "/b", "/c"):
        fetcher.get("https://one.invalid" + path)
    assert transport.paths().count("/robots.txt") == 1 and len(transport.calls) == 4


def test_a_missing_robots_file_allows_everything():
    fetcher, transport, _ = make_fetcher(with_robots("", status=404))
    assert fetcher.get("https://one.invalid/anything").status == 200
    assert transport.paths() == ["/robots.txt", "/anything"]


@pytest.mark.parametrize("status", [401, 403])
def test_a_robots_file_that_is_forbidden_disallows_everything(status):
    fetcher, transport, _ = make_fetcher(with_robots("", status=status))
    with pytest.raises(common.Unreachable, match="robots"):
        fetcher.get("https://one.invalid/anything")
    assert transport.paths() == ["/robots.txt"]


@pytest.mark.parametrize("answer", [reply(500), reply(503), reply(429), reply(301), reply(302), OSError("down"), TimeoutError(), ConnectionResetError()])
def test_a_robots_file_that_cannot_be_read_makes_the_host_unreachable_and_nothing_is_requested(answer):
    def handler(url, headers):
        return answer if url.endswith("/robots.txt") else reply(200, {"n": 1})

    fetcher, transport, _ = make_fetcher(handler)
    for path in ("/a", "/b"):
        with pytest.raises(common.Unreachable, match="robots"):
            fetcher.get("https://one.invalid" + path)
    assert transport.paths() == ["/robots.txt"]  # (one try for the run: a failed read is not asked again)


def redirects(chain: dict[str, tuple], rest=None):
    """A handler: the addresses of ``chain`` answer as given, any robots.txt that is not there is missing, and everything else is a small JSON object."""

    def handler(url, headers):
        if url in chain:
            return chain[url]
        if url.endswith("/robots.txt") or url.endswith("/Robots.txt"):
            return reply(404)
        return rest(url) if rest else reply(200, {"n": 1})

    return handler


def moved(location: str, status: int = 301):
    return reply(status, "", {"Location": location})


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_robots_file_that_has_moved_within_the_site_is_followed_and_every_step_is_paced(status):
    handler = redirects({"https://one.invalid/robots.txt": moved("https://one.invalid/Robots.txt", status)})
    fetcher, transport, _ = make_fetcher(handler)
    assert fetcher.get("https://one.invalid/a").status == 200
    assert transport.paths() == ["/robots.txt", "/Robots.txt", "/a"]  # (a wiki that serves its robots file as a page and sends /robots.txt there)
    assert transport.starts == [0.0, 1.0, 2.0]


def test_the_place_a_robots_file_has_moved_to_may_be_given_as_a_path():
    handler = redirects({"https://one.invalid/robots.txt": moved("/elsewhere/robots-rules.txt"), "https://one.invalid/elsewhere/robots-rules.txt": reply(200, "User-agent: *\nDisallow: /nope")})
    fetcher, transport, _ = make_fetcher(handler)
    with pytest.raises(common.Unreachable, match="robots"):
        fetcher.get("https://one.invalid/nope")
    assert fetcher.get("https://one.invalid/fine").status == 200
    assert transport.paths() == ["/robots.txt", "/elsewhere/robots-rules.txt", "/fine"]


def test_the_rules_of_the_file_a_robots_file_has_moved_to_are_the_rules():
    handler = redirects({"https://one.invalid/robots.txt": moved("https://one.invalid/Robots.txt"), "https://one.invalid/Robots.txt": reply(200, "User-agent: *\nDisallow: /api.php")})
    fetcher, transport, _ = make_fetcher(handler)
    with pytest.raises(common.Unreachable, match="does not allow /api.php"):
        fetcher.get("https://one.invalid/api.php?x=1")
    assert transport.paths() == ["/robots.txt", "/Robots.txt"]


def test_a_robots_file_may_move_five_times_and_no_more():
    steps = [f"https://one.invalid/hop{n}.txt" for n in range(1, 7)]
    chain = {"https://one.invalid/robots.txt": moved(steps[0])}
    chain.update({steps[n]: moved(steps[n + 1]) for n in range(5)})  # robots.txt -> hop1 -> ... -> hop6 (six moves)
    chain[steps[5]] = reply(404)
    fetcher, transport, _ = make_fetcher(redirects(chain))
    with pytest.raises(common.Unreachable, match="more than 5 redirects"):
        fetcher.get("https://one.invalid/a")
    assert len(transport.calls) == 6  # (the first try and five moves; the sixth is not followed)
    chain = {"https://one.invalid/robots.txt": moved(steps[0])}
    chain.update({steps[n]: moved(steps[n + 1]) for n in range(4)})  # five moves in all
    chain[steps[4]] = reply(404)
    fetcher, transport, _ = make_fetcher(redirects(chain))
    assert fetcher.get("https://one.invalid/a").status == 200
    assert len(transport.calls) == 7


def test_a_robots_file_that_moves_in_a_circle_makes_the_host_unreachable():
    chain = {"https://one.invalid/robots.txt": moved("https://one.invalid/Robots.txt"), "https://one.invalid/Robots.txt": moved("https://one.invalid/robots.txt")}
    fetcher, transport, _ = make_fetcher(redirects(chain))
    with pytest.raises(common.Unreachable, match="redirects"):
        fetcher.get("https://one.invalid/a")
    assert len(transport.calls) <= 6 and not any(path == "/a" for path in transport.paths())


@pytest.mark.parametrize("target", ["https://two.invalid/robots.txt", "http://one.invalid/robots.txt", "//two.invalid/robots.txt", "file:///etc/hostname", "javascript:alert(1)", "ftp://one.invalid/robots.txt"])
def test_a_robots_file_that_moves_to_another_site_or_kind_of_address_is_not_followed(target):
    fetcher, transport, _ = make_fetcher(redirects({"https://one.invalid/robots.txt": moved(target)}))
    with pytest.raises(common.Unreachable, match="robots"):
        fetcher.get("https://one.invalid/a")
    assert transport.paths() == ["/robots.txt"] and all("two.invalid" not in url for url in transport.urls)


def test_a_robots_file_that_moves_and_gives_no_place_makes_the_host_unreachable():
    fetcher, transport, _ = make_fetcher(redirects({"https://one.invalid/robots.txt": reply(301)}))
    with pytest.raises(common.Unreachable, match="HTTP 301"):
        fetcher.get("https://one.invalid/a")
    assert transport.paths() == ["/robots.txt"]


def test_a_page_that_has_moved_is_still_not_followed_whatever_robots_says():
    handler = redirects({"https://one.invalid/a": moved("https://one.invalid/b")})
    fetcher, transport, _ = make_fetcher(handler)
    with pytest.raises(common.Unreachable, match="HTTP 301"):
        fetcher.get("https://one.invalid/a")
    assert transport.paths() == ["/robots.txt", "/a"]


def test_a_crawl_delay_slows_the_pace_after_it_is_read():
    fetcher, transport, _ = make_fetcher(with_robots("User-agent: *\nCrawl-delay: 3"))
    fetcher.get("https://one.invalid/a")
    fetcher.get("https://one.invalid/b")
    assert transport.starts == [0.0, 3.0, 6.0]


def test_a_crawl_delay_longer_than_the_check_will_wait_makes_the_host_unreachable():
    fetcher, transport, _ = make_fetcher(with_robots("User-agent: *\nCrawl-delay: 600"))
    with pytest.raises(common.Unreachable, match="delay"):
        fetcher.get("https://one.invalid/a")
    assert transport.paths() == ["/robots.txt"]


def test_robots_can_be_left_out_for_the_apis_of_the_registries():
    fetcher, transport, _ = make_fetcher(with_robots("User-agent: *\nDisallow: /"), honour_robots=False)
    assert fetcher.get("https://one.invalid/a").status == 200
    assert transport.paths() == ["/a"]


# ---- a bad answer is "unreachable", never a change ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [204, 301, 302, 304, 400, 401, 403, 404, 410, 429, 500, 502, 503])
def test_an_answer_that_is_not_a_200_is_unreachable(status):
    fetcher, transport, _ = make_fetcher(lambda url, headers: reply(status, {"n": 1}), honour_robots=False)
    with pytest.raises(common.Unreachable) as caught:
        fetcher.get("https://one.invalid/a")
    assert caught.value.reason.startswith(f"HTTP {status}")
    assert len(transport.calls) == 1  # nothing is followed and nothing is tried again


@pytest.mark.parametrize(
    "error",
    [
        OSError("boom"),
        TimeoutError("boom"),
        ConnectionResetError("boom"),
        urllib.error.URLError("boom"),
        http.client.IncompleteRead(b"boom"),
        http.client.RemoteDisconnected("boom"),
    ],
)
def test_a_network_failure_is_unreachable_and_names_only_its_kind(error):
    fetcher, _, _ = make_fetcher(lambda url, headers: error, honour_robots=False)
    with pytest.raises(common.Unreachable) as caught:
        fetcher.get("https://one.invalid/a")
    assert type(error).__name__ in caught.value.reason and "boom" not in caught.value.reason


def test_a_reason_never_carries_text_of_the_answer():
    page = "<html>please <b>click</b> here to claim your prize</html>"
    fetcher, _, _ = make_fetcher(lambda url, headers: reply(500, page), honour_robots=False)
    with pytest.raises(common.Unreachable) as caught:
        fetcher.get("https://one.invalid/a")
    assert "prize" not in caught.value.reason and "<" not in caught.value.reason
    fetcher, _, _ = make_fetcher(lambda url, headers: reply(200, page), honour_robots=False)
    with pytest.raises(common.Unreachable) as caught:
        fetcher.get_json("https://one.invalid/a")
    assert "prize" not in caught.value.reason and "<" not in caught.value.reason


@pytest.mark.parametrize("body", ["<html><body>Maintenance</body></html>", "", "   ", "{\"n\": ", "not json", "\x00\x01", "{'n': 1}", "NaN NaN", "NaN", "[1, Infinity]"])
def test_an_answer_that_is_not_json_where_json_is_expected_is_unreachable(body):
    fetcher, _, _ = make_fetcher(lambda url, headers: reply(200, body, {"Content-Type": "text/html"}), honour_robots=False)
    with pytest.raises(common.Unreachable, match="JSON"):
        fetcher.get_json("https://one.invalid/a")


def test_an_answer_with_bytes_that_are_not_utf8_is_unreachable():
    fetcher, _, _ = make_fetcher(lambda url, headers: reply(200, b"\xff\xfe{}"), honour_robots=False)
    with pytest.raises(common.Unreachable, match="JSON"):
        fetcher.get_json("https://one.invalid/a")


def test_json_is_returned_as_it_is_whatever_its_type():
    for value in ({"n": 1}, [1, 2], None, "text", 3):
        fetcher, _, _ = make_fetcher(lambda url, headers, value=value: reply(200, json.dumps(value)), honour_robots=False)
        assert fetcher.get_json("https://one.invalid/a") == value


def test_a_json_body_with_a_byte_order_mark_is_read():
    fetcher, _, _ = make_fetcher(lambda url, headers: reply(200, b"\xef\xbb\xbf" + b'{"n": 1}'), honour_robots=False)
    assert fetcher.get_json("https://one.invalid/a") == {"n": 1}


def test_a_gzip_answer_is_unpacked_by_its_header_or_by_its_first_bytes():
    fetcher, _, _ = make_fetcher(lambda url, headers: reply(200, {"n": 1}, gz=True), honour_robots=False)
    assert fetcher.get_json("https://one.invalid/a") == {"n": 1}
    fetcher, _, _ = make_fetcher(lambda url, headers: (200, {}, gzip.compress(b'{"n": 2}')), honour_robots=False)
    assert fetcher.get_json("https://one.invalid/a") == {"n": 2}


def test_a_gzip_answer_that_is_damaged_is_unreachable():
    cut = gzip.compress(b'{"n": 1}' * 100)[:-9]
    fetcher, _, _ = make_fetcher(lambda url, headers: (200, {"Content-Encoding": "gzip"}, cut), honour_robots=False)
    with pytest.raises(common.Unreachable):
        fetcher.get("https://one.invalid/a")


def damaged_gzip_bodies() -> dict[str, bytes]:
    whole = gzip.compress(b'{"n": 1}' * 100)
    flipped = bytearray(whole)
    flipped[len(flipped) // 2] ^= 0xFF  # (a byte in the middle of the compressed data)
    bad_checksum = bytearray(whole)
    bad_checksum[-8] ^= 0xFF  # (the CRC-32 in the trailer)
    return {
        "text that says it is gzip": b'{"n": 1}',
        "the magic number and garbage": b"\x1f\x8b" + b"garbage garbage garbage",
        "a byte flipped inside": bytes(flipped),
        "a wrong checksum": bytes(bad_checksum),
        "cut before the trailer": whole[:-8],
        "cut after the header": whole[:12],
        "empty": b"",
        "bytes after the stream": whole + b"trailing text that is no gzip member",
    }


@pytest.mark.parametrize("what", list(damaged_gzip_bodies()))
def test_a_gzip_answer_that_is_corrupt_is_unreachable_and_never_a_crash(what):
    body = damaged_gzip_bodies()[what]
    fetcher, _, _ = make_fetcher(lambda url, headers: (200, {"Content-Encoding": "gzip"}, body), honour_robots=False)
    try:
        fetcher.get("https://one.invalid/a")
    except common.Unreachable as error:
        assert "gzip" in error.reason or "JSON" in error.reason or "damaged" in error.reason, error.reason
    else:
        assert what == "empty"  # (an empty answer with the header is an empty body, which is no JSON when it is read as JSON: that is `get_json`)
        with pytest.raises(common.Unreachable):
            fetcher.get_json("https://one.invalid/a")


@pytest.mark.parametrize("what", ["a byte flipped inside", "a wrong checksum", "cut before the trailer", "the magic number and garbage"])
def test_a_corrupt_robots_txt_in_gzip_leaves_the_host_alone(what):
    body = damaged_gzip_bodies()[what]

    def handler(url, headers):
        return (200, {"Content-Encoding": "gzip"}, body) if url.endswith("/robots.txt") else reply(200, {"n": 1})

    fetcher, transport, _ = make_fetcher(handler)
    with pytest.raises(common.Unreachable, match=r"robots\.txt of one\.invalid could not be read \(the answer is damaged"):
        fetcher.get("https://one.invalid/a")
    assert transport.paths() == ["/robots.txt"]


def test_what_follows_a_complete_gzip_member_is_decided_as_follows_zero_padding_and_more_members_are_read_and_anything_else_refuses_the_answer():
    first, second, single = gzip.compress(b'{"n": 1,'), gzip.compress(b' "m": 2}'), gzip.compress(b'{"n": 1}')
    padded = first + b"\x00\x00\x00\x00" + second
    fetcher, _, _ = make_fetcher(lambda url, headers: (200, {"Content-Encoding": "gzip"}, padded), honour_robots=False)
    assert fetcher.get_json("https://one.invalid/a") == {"n": 1, "m": 2}  # (concatenated members are one stream, as RFC 1952 has them)
    fetcher, _, _ = make_fetcher(lambda url, headers: (200, {"Content-Encoding": "gzip"}, single + b"\x00\x00"), honour_robots=False)
    assert fetcher.get_json("https://one.invalid/a") == {"n": 1}  # (zero padding after the last member is ignored)
    fetcher, _, _ = make_fetcher(lambda url, headers: (200, {"Content-Encoding": "gzip"}, single + b"text after the member"), honour_robots=False)
    with pytest.raises(common.Unreachable, match=r"damaged \(gzip\)"):
        fetcher.get("https://one.invalid/a")  # (anything else after a member is not an answer that can be trusted)


@pytest.mark.parametrize("names", [("CONTENT-ENCODING", "CONTENT-LENGTH"), ("content-encoding", "content-length"), ("Content-Encoding", "Content-Length"), ("cOnTeNt-EnCoDiNg", "CoNtEnT-lEnGtH")])
def test_the_headers_that_matter_are_found_whatever_case_a_server_writes_them_in(names):
    encoding, length = names
    packed = gzip.compress(json.dumps({"n": 1}).encode("utf-8"))

    def handler(url, headers):
        return (200, {encoding: "gzip", length: str(len(packed))}, packed)

    fetcher, _, _ = make_fetcher(handler, honour_robots=False)
    reply_ = fetcher.get("https://one.invalid/a")
    assert json.loads(reply_.body) == {"n": 1} and set(reply_.headers) == {"content-encoding", "content-length"}  # (the names the fetcher hands on are lower case)


def test_a_redirect_of_robots_txt_is_followed_whatever_case_the_location_header_is_in():
    def handler(url, headers):
        if url == "https://one.invalid/robots.txt":
            return (301, {"LOCATION": "/real-robots.txt"}, b"")
        if url == "https://one.invalid/real-robots.txt":
            return reply(200, "User-agent: *\nDisallow: /private/\n")
        return reply(200, {"n": 1})

    fetcher, transport, _ = make_fetcher(handler)
    with pytest.raises(common.Unreachable, match="does not allow /private/x"):
        fetcher.get("https://one.invalid/private/x")
    assert transport.paths() == ["/robots.txt", "/real-robots.txt"]


def test_an_answer_cut_short_is_found_whatever_case_the_content_length_is_in(cutting_headers_in_other_case):
    with pytest.raises(common.Unreachable, match="cut short"):
        real_fetcher().get(cutting_headers_in_other_case + "/cut")


def test_an_answer_over_the_size_limit_is_unreachable_packed_or_unpacked():
    fetcher, _, _ = make_fetcher(lambda url, headers: reply(200, b"x" * 2000), honour_robots=False, max_bytes=1000)
    with pytest.raises(common.Unreachable, match="large"):
        fetcher.get("https://one.invalid/a")
    bomb = gzip.compress(b"\x00" * 20_000_000)
    assert len(bomb) < 100_000
    fetcher, _, _ = make_fetcher(lambda url, headers: (200, {"Content-Encoding": "gzip"}, bomb), honour_robots=False, max_bytes=100_000)
    with pytest.raises(common.Unreachable, match="large"):
        fetcher.get("https://one.invalid/a")


def test_a_run_goes_on_after_an_unreachable_answer():
    answers = iter([reply(500), reply(200, {"n": 1})])
    fetcher, _, _ = make_fetcher(lambda url, headers: next(answers), honour_robots=False)
    with pytest.raises(common.Unreachable):
        fetcher.get("https://one.invalid/a")
    assert fetcher.get_json("https://one.invalid/b") == {"n": 1}


# ---- the real transport, on the loopback address ---------------------------------------------------------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: list[dict] = []

    def log_message(self, *args):  # silence
        pass

    def do_GET(self):
        type(self).seen.append({"path": self.path, "headers": {name.lower(): value for name, value in self.headers.items()}})
        if self.path == "/redirect":
            self.send_response(301)
            self.send_header("Location", "/json")
            self.end_headers()
        elif self.path == "/gz":
            body = gzip.compress(b'{"zipped": true}')
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/missing":
            body = b"<html>no such page</html>"
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = b'{"n": 1}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


@pytest.fixture
def loopback():
    _Handler.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def real_fetcher():
    fake_time = FakeTime()
    return common.Fetcher(USER_AGENT, transport=common.real_transport(timeout=10), clock=fake_time.clock, sleep=fake_time.sleep, honour_robots=False)


def test_the_real_transport_sends_the_headers_and_reads_json(loopback):
    assert real_fetcher().get_json(loopback + "/json") == {"n": 1}
    (seen,) = _Handler.seen
    assert seen["headers"]["user-agent"] == USER_AGENT and seen["headers"]["accept-encoding"] == "gzip"


def test_the_real_transport_unpacks_gzip(loopback):
    assert real_fetcher().get_json(loopback + "/gz") == {"zipped": True}


def test_the_real_transport_does_not_follow_a_redirect(loopback):
    with pytest.raises(common.Unreachable, match="HTTP 301"):
        real_fetcher().get(loopback + "/redirect")
    assert [seen["path"] for seen in _Handler.seen] == ["/redirect"]


def test_the_real_transport_reports_an_error_status_as_an_answer(loopback):
    with pytest.raises(common.Unreachable, match="HTTP 404"):
        real_fetcher().get(loopback + "/missing")


def test_the_real_transport_to_a_port_nothing_listens_on_is_unreachable():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    server.server_close()  # (the port is free again, and nothing answers on it)
    with pytest.raises(common.Unreachable):
        real_fetcher().get(f"http://127.0.0.1:{port}/json")


# ---- a body that stops before its Content-Length is a cut answer, never a short one ---------------------------------------------------------------------------

JSON_BODY = b'{"license": "kept", "items": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]}'


def send_cut(handler, status, body, keep, *headers):
    """An answer that promises all of ``body`` and stops after ``keep`` bytes: the server closes the connection there."""
    handler.send_response(status)
    for name, value in headers:
        handler.send_header(name, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body[:keep])
    handler.wfile.flush()
    handler.close_connection = True


class _CutHandler(http.server.BaseHTTPRequestHandler):
    seen: list[str] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        type(self).seen.append(self.path)
        if self.path == "/cut-json":
            send_cut(self, 200, JSON_BODY, 12)
        elif self.path == "/cut-gz":
            packed = gzip.compress(JSON_BODY * 4)
            send_cut(self, 200, packed, len(packed) // 2, ("Content-Encoding", "gzip"))
        elif self.path == "/cut-error":
            send_cut(self, 503, b"<html>the service is unavailable, and it says so at some length</html>", 10)
        elif self.path in ("/cut-401", "/cut-403", "/cut-429"):
            send_cut(self, int(self.path[-3:]), b"<html>no, and it says so at some length</html>", 10)
        elif self.path == "/stall-403":
            send_cut(self, 403, b"<html>no, and it says so at some length</html>", 5)  # (the connection stays open: the rest of the body never comes)
            time.sleep(2.5)
        elif self.path == "/cut-before-the-body":
            send_cut(self, 200, JSON_BODY, 0)
        elif self.path == "/not-modified":
            send_cut(self, 304, b"x" * 120, 0)
        elif self.path == "/whole":
            send_cut(self, 200, JSON_BODY, len(JSON_BODY))
        elif self.path == "/no-length":
            self.send_response(200)  # (HTTP/1.0 with no Content-Length: the body ends where the connection does)
            self.end_headers()
            self.wfile.write(JSON_BODY)
        elif self.path == "/robots.txt":
            send_cut(self, 200, b"User-agent: *\nAllow: /public/\nDisallow: /private/\n", 15)  # (it is cut before it says what is forbidden)
        else:
            send_cut(self, 200, JSON_BODY, len(JSON_BODY))


@pytest.fixture
def cutting():
    _CutHandler.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CutHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


class _UpperCaseHandler(http.server.BaseHTTPRequestHandler):
    """A server that writes its header names in capitals and cuts the body short."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("CONTENT-LENGTH", str(len(JSON_BODY)))
        self.end_headers()
        self.wfile.write(JSON_BODY[:12])
        self.wfile.flush()
        self.close_connection = True


@pytest.fixture
def cutting_headers_in_other_case():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _UpperCaseHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


@pytest.mark.parametrize("path", ["/cut-json", "/cut-gz", "/cut-before-the-body"])
def test_a_body_that_stops_before_its_content_length_is_unreachable_and_never_accepted(cutting, path):
    with pytest.raises(common.Unreachable, match="cut short"):
        real_fetcher().get(cutting + path)


def test_a_cut_json_is_unreachable_so_that_it_cannot_give_a_new_hash_and_a_changed(cutting):
    with pytest.raises(common.Unreachable, match="cut short"):
        real_fetcher().get_json(cutting + "/cut-json")


def test_the_real_transport_raises_on_a_cut_200_body_and_hands_on_the_status_of_an_error_whose_body_is_cut(cutting):
    transport = common.real_transport(timeout=10)
    with pytest.raises(http.client.IncompleteRead):
        transport(cutting + "/cut-json", {"User-Agent": USER_AGENT})
    status, headers, body = transport(cutting + "/cut-error", {"User-Agent": USER_AGENT})
    assert (status, body) == (503, b"") and headers  # (the body of an answer that is not a 200 is never used: what is known is its status)


def test_an_error_status_whose_body_is_cut_is_that_status_and_not_a_cut_answer(cutting):
    with pytest.raises(common.Unreachable) as caught:
        real_fetcher().get(cutting + "/cut-error")
    assert caught.value.reason == "HTTP 503"


@pytest.mark.parametrize("status", [401, 403, 429])
def test_a_refusal_whose_body_is_cut_short_still_refuses_the_host_and_the_second_path_is_not_asked(cutting, status):
    fetcher = real_fetcher()
    with pytest.raises(common.Unreachable) as first:
        fetcher.get(f"{cutting}/cut-{status}")
    assert first.value.reason == f"HTTP {status}"
    with pytest.raises(common.Unreachable, match="earlier in this run; the host is not asked again"):
        fetcher.get(f"{cutting}/whole")
    assert _CutHandler.seen == [f"/cut-{status}"]  # (nothing was sent for the second path)


def test_a_refusal_whose_body_times_out_still_refuses_the_host_and_the_second_path_is_not_asked(cutting):
    fake_time = FakeTime()
    fetcher = common.Fetcher(USER_AGENT, transport=common.real_transport(timeout=0.5), clock=fake_time.clock, sleep=fake_time.sleep, honour_robots=False)
    with pytest.raises(common.Unreachable) as first:
        fetcher.get(f"{cutting}/stall-403")
    assert first.value.reason == "HTTP 403"
    with pytest.raises(common.Unreachable, match="earlier in this run"):
        fetcher.get(f"{cutting}/whole")
    assert _CutHandler.seen == ["/stall-403"]


def test_a_cut_robots_txt_that_is_a_refusal_leaves_the_host_alone_all_the_same(cutting):
    # (the loopback server's /robots.txt is a 200 cut short; this one is asked for a path whose robots.txt is a 403 with a cut body, by the fetcher that honours robots.txt)
    def handler(url, headers):
        return (403, {"Content-Length": "100"}, b"") if url.endswith("/robots.txt") else reply(200, {"n": 1})

    fetcher, transport, _ = make_fetcher(handler)
    for path in ("/a", "/b"):
        with pytest.raises(common.Unreachable):
            fetcher.get("https://one.invalid" + path)
    assert transport.paths() == ["/robots.txt"]


def test_a_cut_robots_txt_leaves_the_host_alone_and_does_not_allow_what_it_forbade(cutting):
    fake_time = FakeTime()
    fetcher = common.Fetcher(USER_AGENT, transport=common.real_transport(timeout=10), clock=fake_time.clock, sleep=fake_time.sleep)
    with pytest.raises(common.Unreachable, match=r"robots\.txt of 127\.0\.0\.1:\d+ could not be read \(the answer was cut short"):
        fetcher.get(cutting + "/private/data.json")
    assert _CutHandler.seen == ["/robots.txt"]  # (nothing else was asked for)
    with pytest.raises(common.Unreachable, match="could not be read"):
        fetcher.get(cutting + "/public/data.json")
    assert _CutHandler.seen == ["/robots.txt"]  # (and the reading of robots.txt is not tried again in the run)


def test_an_answer_that_is_whole_or_has_no_length_is_still_read(cutting):
    assert real_fetcher().get_json(cutting + "/whole")["license"] == "kept"
    assert real_fetcher().get_json(cutting + "/no-length")["license"] == "kept"


def test_an_answer_that_has_no_body_by_its_status_is_not_called_cut(cutting):
    # (a 304 may carry the Content-Length of the page it stands for, and has no body: it is an answer that is not a 200, and not a cut one)
    with pytest.raises(common.Unreachable, match=r"^HTTP 304"):
        real_fetcher().get(cutting + "/not-modified")


@pytest.mark.parametrize("url", ["file:///etc/hostname", "ftp://one.invalid/a", "javascript:alert(1)", "//one.invalid/a", "one.invalid/a"])
def test_the_real_transport_asks_for_http_and_https_only(url):
    with pytest.raises(ValueError):
        common.real_transport(timeout=5)(url, {})


# ---- a host that refuses is left alone for the rest of the run --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 429])
def test_a_host_that_refuses_is_not_asked_again_in_the_run(status):
    fetcher, transport, _ = make_fetcher(lambda url, headers: reply(status), honour_robots=False)
    with pytest.raises(common.Unreachable) as first:
        fetcher.get("https://one.invalid/a")
    assert first.value.reason == f"HTTP {status}"
    for path in ("/b", "/a", "/c?x=1"):
        with pytest.raises(common.Unreachable) as again:
            fetcher.get("https://one.invalid" + path)
        assert again.value.reason == f"HTTP {status} earlier in this run; the host is not asked again"
    assert len(transport.calls) == 1 and fetcher.requests == 1  # (nothing was sent after the first answer)


def test_a_host_that_asks_for_a_wait_is_not_asked_again_in_the_run_either():
    fetcher, transport, _ = make_fetcher(lambda url, headers: reply(429, b"slow down", {"Retry-After": "120"}), honour_robots=False)
    for _ in range(3):
        with pytest.raises(common.Unreachable):
            fetcher.get("https://one.invalid/a")
    assert len(transport.calls) == 1


def test_the_refusal_is_of_that_host_and_the_others_are_asked():
    def handler(url, headers):
        return reply(403) if "one.invalid" in url else reply(200, {"n": 1})

    fetcher, transport, _ = make_fetcher(handler, honour_robots=False)
    with pytest.raises(common.Unreachable):
        fetcher.get("https://one.invalid/a")
    assert fetcher.get_json("https://two.invalid/a") == {"n": 1}
    assert fetcher.get_json("https://two.invalid/b") == {"n": 1}
    with pytest.raises(common.Unreachable, match="earlier in this run"):
        fetcher.get("https://one.invalid/b")
    assert transport.urls == ["https://one.invalid/a", "https://two.invalid/a", "https://two.invalid/b"]


@pytest.mark.parametrize("status", [400, 404, 410, 500, 502, 503])
def test_any_other_status_is_not_a_refusal_and_the_next_request_is_sent(status):
    fetcher, transport, _ = make_fetcher(lambda url, headers: reply(status), honour_robots=False)
    for path in ("/a", "/b"):
        with pytest.raises(common.Unreachable) as caught:
            fetcher.get("https://one.invalid" + path)
        assert caught.value.reason.startswith(f"HTTP {status}") and "earlier" not in caught.value.reason
    assert len(transport.calls) == 2


def test_a_refusal_after_a_good_robots_txt_stops_the_requests_of_that_host():
    def handler(url, headers):
        return reply(404) if url.endswith("/robots.txt") else reply(403)

    fetcher, transport, _ = make_fetcher(handler)
    for path in ("/a", "/b", "/c"):
        with pytest.raises(common.Unreachable):
            fetcher.get("https://one.invalid" + path)
    assert transport.paths() == ["/robots.txt", "/a"]


def test_a_refusal_of_robots_txt_itself_stops_the_requests_too():
    for status in (401, 403, 429):
        fetcher, transport, _ = make_fetcher(lambda url, headers: reply(status))
        for path in ("/a", "/b"):
            with pytest.raises(common.Unreachable):
                fetcher.get("https://one.invalid" + path)
        assert transport.paths() == ["/robots.txt"], status


# ---- the log of a run: a trace for a task that has no window ------------------------------------------------------------------------------------------------


def test_a_log_line_is_the_utc_time_the_outcome_and_the_text_on_one_line():
    assert common.log_line(NOW, "ok", "2 titles changed; report x.md") == "2026-10-18T12:00:00Z ok 2 titles changed; report x.md"
    plus_two = datetime.timezone(datetime.timedelta(hours=2))
    assert common.log_line(datetime.datetime(2026, 10, 18, 14, 0, 0, tzinfo=plus_two), "refused", "no catalog") == "2026-10-18T12:00:00Z refused no catalog"


def test_a_log_line_has_no_line_break_and_is_cut_to_a_line():
    line = common.log_line(NOW, "error", "first\r\nsecond\tthird fourth " + "x" * 1000)
    assert line.startswith("2026-10-18T12:00:00Z error first second third fourth x")
    assert not re.search(r"[\x00-\x1f\x7f\x85  ]", line) and line.endswith("...") and len(line) <= 440


@pytest.mark.parametrize("outcome", ["ok", "failed", "refused", "error", "interrupted"])
def test_the_five_outcomes_of_a_run_can_be_logged(outcome):
    assert common.log_line(NOW, outcome, "text").split(" ")[1] == outcome


@pytest.mark.parametrize("outcome", ["", "OK", "maybe", "ok text"])
def test_any_other_outcome_is_refused(outcome):
    with pytest.raises(ValueError):
        common.log_line(NOW, outcome, "text")


def test_a_time_without_a_zone_is_refused_for_a_log_line():
    with pytest.raises(ValueError):
        common.log_line(datetime.datetime(2026, 10, 18, 12, 0, 0), "ok", "text")


def test_a_log_is_made_with_its_folder_and_gets_a_line_for_each_run(tmp_path):
    folder = tmp_path / "not" / "there" / "yet"
    path = common.append_log(folder, "sources-check", NOW, "ok", "first")
    assert path == folder / "sources-check.log"
    common.append_log(folder, "sources-check", NOW + datetime.timedelta(hours=1), "refused", "second")
    assert path.read_text(encoding="utf-8") == "2026-10-18T12:00:00Z ok first\n2026-10-18T13:00:00Z refused second\n"


def test_a_log_keeps_its_last_200_lines(tmp_path):
    for number in range(205):
        common.append_log(tmp_path, "x", NOW + datetime.timedelta(seconds=number), "ok", f"run {number}")
    lines = (tmp_path / "x.log").read_text(encoding="utf-8").splitlines()
    assert common.LOG_LINES == 200 and len(lines) == 200
    assert lines[0].endswith(" ok run 5") and lines[-1].endswith(" ok run 204")


def test_a_log_that_is_longer_than_that_is_cut_at_its_next_line_and_its_blank_lines_go(tmp_path):
    (tmp_path / "x.log").write_text("".join(f"2026-01-01T00:00:00Z ok old {n}\n\n" for n in range(300)), encoding="utf-8")
    common.append_log(tmp_path, "x", NOW, "ok", "new")
    lines = (tmp_path / "x.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 200 and lines[0].endswith("old 101") and lines[-1] == "2026-10-18T12:00:00Z ok new" and "" not in lines


def test_a_log_with_damaged_bytes_or_no_last_line_end_is_still_added_to(tmp_path):
    (tmp_path / "x.log").write_bytes(b"2026-01-01T00:00:00Z ok \xff\xfe broken")
    common.append_log(tmp_path, "x", NOW, "ok", "new")
    lines = (tmp_path / "x.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[0].startswith("2026-01-01T00:00:00Z ok ") and lines[1] == "2026-10-18T12:00:00Z ok new"


def test_a_log_that_cannot_be_written_is_no_failure_of_the_run(tmp_path):
    (tmp_path / "x.log").mkdir()  # (a folder where the file should be)
    assert common.append_log(tmp_path, "x", NOW, "ok", "line") is None
    blocked = tmp_path / "a-file"
    blocked.write_text("not a folder", encoding="utf-8")
    assert common.append_log(blocked / "inside", "x", NOW, "ok", "line") is None


# ---- the stamps the release build reads --------------------------------------------------------------------------------------------------------------------


def test_a_stamp_is_the_utc_time_to_the_second_with_a_Z_and_a_line_end():
    assert common.stamp_text(datetime.datetime(2026, 10, 18, 10, 0, 3, 987654, tzinfo=datetime.timezone.utc)) == "2026-10-18T10:00:03Z\n"
    plus_two = datetime.timezone(datetime.timedelta(hours=2))
    assert common.stamp_text(datetime.datetime(2026, 10, 18, 12, 0, 0, tzinfo=plus_two)) == "2026-10-18T10:00:00Z\n"


def test_a_time_without_a_zone_is_refused_for_a_stamp():
    with pytest.raises(ValueError):
        common.stamp_text(datetime.datetime(2026, 10, 18, 10, 0, 3))


def test_the_utc_text_of_a_time_is_read_back_to_the_same_second():
    when = datetime.datetime(2026, 10, 18, 10, 0, 3, tzinfo=datetime.timezone.utc)
    assert common.parse_utc(common.utc_text(when)) == when
    assert common.parse_utc("2026-10-18T10:00:03+00:00") == when
    for bad in ("", "yesterday", "2026-13-45T00:00:00Z", None, 5):
        with pytest.raises(ValueError):
            common.parse_utc(bad)


@pytest.mark.parametrize("name", release.SCHEDULED_CHECKS)
def test_the_release_build_reads_a_stamp_written_by_the_checks(tmp_path, name):
    common.write_stamp(tmp_path / "checks", name, NOW - datetime.timedelta(days=3))
    assert (tmp_path / "checks" / f"{name}.last-run").read_text(encoding="utf-8") == common.stamp_text(NOW - datetime.timedelta(days=3))
    assert release.scheduled_warnings(tmp_path / "checks", NOW, names=[name]) == []
    common.write_stamp(tmp_path / "checks", name, NOW - datetime.timedelta(days=11))
    (warning,) = release.scheduled_warnings(tmp_path / "checks", NOW, names=[name])
    assert name in warning and "11 days" in warning


def test_a_stamp_written_now_gives_no_warning_and_a_second_stamp_replaces_the_first(tmp_path):
    for name in release.SCHEDULED_CHECKS:
        common.write_stamp(tmp_path, name, NOW - datetime.timedelta(days=40))
    assert len(release.scheduled_warnings(tmp_path, NOW)) == len(release.SCHEDULED_CHECKS)
    for name in release.SCHEDULED_CHECKS:
        common.write_stamp(tmp_path, name, NOW)
    assert release.scheduled_warnings(tmp_path, NOW) == []
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(f"{name}.last-run" for name in release.SCHEDULED_CHECKS)  # (no temporary file is left)


def test_a_write_that_fails_keeps_the_old_file_and_leaves_no_temporary_file(tmp_path, monkeypatch):
    target = tmp_path / "a.txt"
    common.write_text_atomic(target, "old\n")

    def refuse(*args, **kwargs):
        raise OSError("no")

    monkeypatch.setattr(common.os, "replace", refuse)
    with pytest.raises(OSError):
        common.write_text_atomic(target, "new\n")
    assert target.read_text(encoding="utf-8") == "old\n" and [p.name for p in tmp_path.iterdir()] == ["a.txt"]


def test_text_is_written_with_unix_line_ends_and_in_utf8(tmp_path):
    common.write_text_atomic(tmp_path / "a" / "b.md", "line\nCafé\n")
    assert (tmp_path / "a" / "b.md").read_bytes() == "line\nCafé\n".encode("utf-8")


# ---- code spans -------------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, rendered",
    [
        ("Zorblax Ring", "`Zorblax Ring`"),
        ("Al`Kabor's Cap", "``Al`Kabor's Cap``"),
        ("`quoted`", "`` `quoted` ``"),
        ("a``b", "```a``b```"),
        ("a`b``c", "```a`b``c```"),
        ("line\nbreak\r\nhere", "`line break here`"),
        (" padded ", "`  padded  `"),
        ("tab\there", "`tab here`"),
    ],
)
def test_a_title_is_rendered_as_a_code_span_that_it_cannot_break_out_of(text, rendered):
    assert common.code_span(text) == rendered


def read_code_span(span: str) -> str:
    """What a CommonMark reader shows for a code span: the text between a fence and the next run of backticks as long as it, with one space taken off each end when both ends have one."""
    found = re.fullmatch(r"(`+)(.+?)(?<!`)\1(?!`)", span, re.S)
    assert found, f"{span!r} is not one code span"
    content = found.group(2).replace("\n", " ")
    if content.startswith(" ") and content.endswith(" ") and content.strip(" "):
        content = content[1:-1]
    return content


def test_a_code_span_of_any_text_is_read_back_as_that_text():
    for text in ("`", "``", "```", "a`b", "`a`", " `", "` ", "``a``", "x" * 50 + "`" * 7, "a ` b", "  ", " a ", "Al`Kabor's Cap of Binding", "Ry`Gorr Chain Coif"):
        assert read_code_span(common.code_span(text)) == text
    assert read_code_span(common.code_span("one\ntwo\r\n\tthree")) == "one two three"


# ---- the replay of recorded answers (the dry run) -----------------------------------------------------------------------------------------------------------


def write_replay(folder: Path, entries: list[dict], files: dict[str, str] | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in (files or {}).items():
        (folder / name).write_text(text, encoding="utf-8")
    (folder / "replay.json").write_text(json.dumps({"responses": entries}), encoding="utf-8")
    return folder


def test_a_replay_answers_by_address_and_by_the_parts_of_the_query_the_entry_names(tmp_path):
    folder = write_replay(
        tmp_path,
        [
            {"url": "https://one.invalid/robots.txt", "status": 404, "body": ""},
            {"url": "https://one.invalid/api", "query": {"list": "a"}, "status": 200, "body": '{"n": 1}'},
            {"url": "https://one.invalid/api", "query": {"list": "a", "cont": "x"}, "status": 200, "body": '{"n": 2}'},
            {"url": "https://one.invalid/big", "status": 200, "file": "big.json", "headers": {"Content-Type": "application/json"}},
            {"url": "https://one.invalid/slow", "status": 503, "body": "busy"},
        ],
        {"big.json": '{"big": true}'},
    )
    replay = common.ReplayTransport.from_directory(folder)
    assert replay("https://one.invalid/robots.txt", {})[0] == 404
    assert json.loads(replay("https://one.invalid/api?format=json&list=a&rcstart=2026", {})[2]) == {"n": 1}
    assert json.loads(replay("https://one.invalid/api?list=a&cont=x&maxlag=5", {})[2]) == {"n": 2}  # (the entry that names more of the query wins)
    status, headers, body = replay("https://one.invalid/big", {})
    assert (status, headers["Content-Type"], json.loads(body)) == (200, "application/json", {"big": True})
    assert replay("https://one.invalid/slow", {})[0] == 503
    assert len(replay.requests) == 5 and replay.requests[0] == "https://one.invalid/robots.txt"


def test_a_replay_has_no_answer_for_what_it_did_not_record_and_the_fetcher_calls_that_unreachable(tmp_path):
    folder = write_replay(tmp_path, [{"url": "https://one.invalid/robots.txt", "status": 404, "body": ""}])
    replay = common.ReplayTransport.from_directory(folder)
    with pytest.raises(OSError):
        replay("https://one.invalid/elsewhere", {})
    virtual = common.VirtualTime()
    fetcher = common.Fetcher(USER_AGENT, transport=replay, clock=virtual.clock, sleep=virtual.sleep)
    with pytest.raises(common.Unreachable):
        fetcher.get("https://one.invalid/elsewhere")


def test_a_replay_that_cannot_be_read_is_refused_in_one_line(tmp_path):
    for text in ("", "not json", "[]", '{"responses": 3}', '{"responses": [{"status": 200}]}', '{"responses": [{"url": "https://one.invalid/a", "status": "ok"}]}'):
        (tmp_path / "replay.json").write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            common.ReplayTransport.from_directory(tmp_path)
    with pytest.raises(ValueError):
        common.ReplayTransport.from_directory(tmp_path / "no-such-folder")


def test_a_replay_file_cannot_point_outside_its_folder(tmp_path):
    folder = write_replay(tmp_path / "r", [{"url": "https://one.invalid/a", "status": 200, "file": "../secret.txt"}])
    (tmp_path / "secret.txt").write_text("not for the report", encoding="utf-8")
    with pytest.raises(ValueError):
        common.ReplayTransport.from_directory(folder)


def test_the_virtual_time_of_a_dry_run_makes_the_pace_without_waiting():
    virtual = common.VirtualTime()
    virtual.sleep(2.5)
    assert virtual.clock() == 2.5
