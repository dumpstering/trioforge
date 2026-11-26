"""Tests for what the polite client does about robots.txt. Nothing here touches the network.

The standing rule is "scrape politely: one request a second, honour robots and terms". The client reads the robots.txt of a host before the first request to it in a run
(through the same paced transport, counted as a request), refuses what it disallows, obeys a Crawl-delay longer than its own pace, treats a missing file (404) as no
restriction, and stops with a clear error when the file cannot be read. A fake transport, clock and sleep stand in for urllib and the wall clock, and every host and path is
invented.
"""

import http.client
import random
import re
import time
import urllib.error
import urllib.parse

import pytest

from test_http import UA, FakeTime, reply
from trioforge.sources import robots as robots_module
from trioforge.sources.http import API_URL, FetchError, PoliteClient
from trioforge.sources.robots import parse_robots

SITE = "https://wiki.example.invalid"
PAGE = SITE + "/page/one"
OTHER = "https://other.example.invalid/page"
ALLOW_ALL = "User-agent: *\nAllow: /\n"


class Site:
    """A fake transport that answers by address: ``routes`` maps a path (or a full address) to a reply, a list of replies (played in turn, the last one kept) or an exception."""

    def __init__(self, fake_time, routes):
        self.time = fake_time
        self.routes = routes
        self.calls = []  # (start time, address)

    def __call__(self, url, headers):
        self.calls.append((self.time.now, url))
        parts = urllib.parse.urlsplit(url)
        route = self.routes.get(url, self.routes.get(parts.path))
        assert route is not None, "the client asked for an address the test did not expect: " + url
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, BaseException):
            raise route
        return route

    @property
    def paths(self):
        return [urllib.parse.urlsplit(url).path for _when, url in self.calls]

    @property
    def starts(self):
        return [when for when, _url in self.calls]


def text_reply(text, status=200, headers=None):
    return reply(status=status, headers=headers, body=text.encode("utf-8"))


def make(routes, **kwargs):
    fake_time = FakeTime()
    site = Site(fake_time, routes)
    client = PoliteClient(UA, transport=site, clock=fake_time.clock, sleep=fake_time.sleep, **kwargs)
    return client, site, fake_time


def allow_page(url):
    return urllib.parse.urlsplit(url).netloc.endswith(".example.invalid")


PAGE_REPLY = text_reply("<html>fine</html>")


# ---- what robots.txt allows -----------------------------------------------------------------------------------


def test_a_disallowed_address_is_refused_and_nothing_but_robots_txt_is_asked_for():
    client, site, _ = make({"/robots.txt": text_reply("User-agent: *\nDisallow: /page/\n")})
    with pytest.raises(FetchError, match="robots.txt does not allow") as caught:
        client.get_text(PAGE, allow_page)
    assert caught.value.url == PAGE and caught.value.status is None
    assert site.paths == ["/robots.txt"] and client.requests == 1


@pytest.mark.parametrize(
    "robots",
    [
        "User-agent: *\nDisallow: /page/",
        "User-agent: trioforge-extractor\nDisallow: /page/\n\nUser-agent: *\nAllow: /",  # the group for this program wins over the one for everybody
        "User-agent: TrioForge\nDisallow: /page/",  # a group for the front of the name up to a hyphen
        "# a comment\r\nUSER-AGENT: *\r\nDISALLOW: /pa*e/one\r\n",  # field names have no case, a pattern may have a star
        "User-agent: *\nDisallow: /\nAllow: /elsewhere",  # the longest rule decides: /page/one is under Disallow: /
    ],
    ids=["everybody", "this program", "the front of the name", "star and case", "longest rule"],
)
def test_what_robots_txt_disallows_for_this_program_or_for_everybody_is_refused(robots):
    client, site, _ = make({"/robots.txt": text_reply(robots)})
    with pytest.raises(FetchError, match="robots.txt does not allow"):
        client.get_text(PAGE, allow_page)
    assert site.paths == ["/robots.txt"]


@pytest.mark.parametrize(
    "robots",
    [
        ALLOW_ALL,
        "User-agent: otherbot\nDisallow: /",  # a rule for another program is not ours
        "User-agent: *\nDisallow: /page/\nAllow: /page/one",  # the longer Allow wins
        "User-agent: *\nDisallow:",  # an empty Disallow forbids nothing
        "User-agent: trioforge-extractor\nAllow: /\n\nUser-agent: *\nDisallow: /",  # our own group is the one that counts
        "",
    ],
    ids=["allow all", "another bot", "longer allow", "empty disallow", "our group allows", "empty file"],
)
def test_an_address_that_robots_txt_allows_is_asked_for_after_it(robots):
    client, site, _ = make({"/robots.txt": text_reply(robots), "/page/one": PAGE_REPLY})
    assert client.get_text(PAGE, allow_page) == "<html>fine</html>"
    assert site.paths == ["/robots.txt", "/page/one"]


def test_the_query_of_a_json_request_is_part_of_what_robots_txt_is_asked_about():
    # the API of the wiki: /api.php?action=...; a rule for the script with a query decides about it
    routes = {"/robots.txt": text_reply("User-agent: *\nDisallow: /api.php?action=query\n"), "/api.php": reply({"query": {}})}
    client, site, _ = make(routes)
    with pytest.raises(FetchError, match="robots.txt does not allow"):
        client.get_json({"action": "query"})
    assert site.paths == ["/robots.txt"]


def test_the_robots_txt_asked_for_is_the_one_of_the_origin_of_the_address_and_says_who_asks():
    seen = []

    def transport(url, headers):
        seen.append((url, dict(headers)))
        return text_reply(ALLOW_ALL) if url.endswith("/robots.txt") else PAGE_REPLY

    fake_time = FakeTime()
    client = PoliteClient(UA, transport=transport, clock=fake_time.clock, sleep=fake_time.sleep)
    client.get_text(PAGE + "?x=1", allow_page)
    assert [url for url, _headers in seen] == [SITE + "/robots.txt", PAGE + "?x=1"]
    assert all(headers["User-Agent"] == UA for _url, headers in seen)


# ---- the pace and the count -------------------------------------------------------------------------------------


def test_the_robots_txt_goes_through_the_same_pace_and_is_counted_as_a_request():
    client, site, _ = make({"/robots.txt": text_reply(ALLOW_ALL), "/page/one": PAGE_REPLY})
    client.get_text(PAGE, allow_page)
    client.get_text(PAGE, allow_page)
    assert site.starts == [0.0, 1.0, 2.0] and client.requests == 3


def test_a_crawl_delay_longer_than_the_pace_is_obeyed_from_the_next_request_on():
    client, site, _ = make({"/robots.txt": text_reply("User-agent: *\nCrawl-delay: 5\n"), "/page/one": PAGE_REPLY})
    for _ in range(3):
        client.get_text(PAGE, allow_page)
    assert site.paths == ["/robots.txt", "/page/one", "/page/one", "/page/one"]
    assert site.starts == [0.0, 5.0, 10.0, 15.0]
    assert client.min_interval == 5.0


def test_the_crawl_delay_of_the_group_of_this_program_is_the_one_that_counts():
    robots = "User-agent: trioforge-extractor\nCrawl-delay: 2.5\n\nUser-agent: *\nCrawl-delay: 30\n"
    client, site, _ = make({"/robots.txt": text_reply(robots), "/page/one": PAGE_REPLY})
    client.get_text(PAGE, allow_page)
    client.get_text(PAGE, allow_page)
    assert site.starts == [0.0, 2.5, 5.0]


@pytest.mark.parametrize("robots", ["User-agent: *\nCrawl-delay: 0.2", "User-agent: *\nCrawl-delay: 1", "User-agent: otherbot\nCrawl-delay: 30", "User-agent: *\nCrawl-delay: soon"])
def test_a_crawl_delay_that_is_not_longer_than_the_pace_changes_nothing(robots):
    client, site, _ = make({"/robots.txt": text_reply(robots), "/page/one": PAGE_REPLY})
    client.get_text(PAGE, allow_page)
    client.get_text(PAGE, allow_page)
    assert site.starts == [0.0, 1.0, 2.0] and client.min_interval == 1.0


def test_a_crawl_delay_of_more_than_a_minute_stops_the_run_with_a_clear_error():
    client, site, _ = make({"/robots.txt": text_reply("User-agent: *\nCrawl-delay: 120\n"), "/page/one": PAGE_REPLY})
    with pytest.raises(FetchError, match="asks for a delay of 120 s"):
        client.get_text(PAGE, allow_page)
    assert site.paths == ["/robots.txt"]


# ---- a robots.txt that is missing, forbidden or cannot be read ---------------------------------------------------


@pytest.mark.parametrize("status", [404, 410, 400, 451])
def test_a_missing_robots_txt_means_no_restriction(status):
    client, site, _ = make({"/robots.txt": text_reply("not a robots file, Disallow: /", status=status), "/page/one": PAGE_REPLY})
    assert client.get_text(PAGE, allow_page) == "<html>fine</html>"
    assert site.paths == ["/robots.txt", "/page/one"] and client.requests == 2


@pytest.mark.parametrize("status", [401, 403])
def test_a_forbidden_robots_txt_allows_nothing(status):
    client, site, _ = make({"/robots.txt": text_reply("", status=status), "/page/one": PAGE_REPLY})
    with pytest.raises(FetchError, match="robots.txt does not allow"):
        client.get_text(PAGE, allow_page)
    assert site.paths == ["/robots.txt"]


def test_a_server_error_for_robots_txt_stops_the_run_with_a_clear_error_and_the_site_is_not_asked_again():
    client, site, fake_time = make({"/robots.txt": text_reply("", status=503), "/page/one": PAGE_REPLY})
    with pytest.raises(FetchError, match=r"robots\.txt of wiki\.example\.invalid could not be read .*the site is not asked") as caught:
        client.get_text(PAGE, allow_page)
    assert caught.value.status == 503
    tries = len(site.calls)
    assert tries == client.max_retries + 1 and set(site.paths) == {"/robots.txt"}  # (the client's own retries, with its own back off: nothing but the robots.txt is asked for)
    with pytest.raises(FetchError, match="could not be read"):
        client.get_text(PAGE, allow_page)
    assert len(site.calls) == tries  # (kept for the run: not asked again)
    assert fake_time.now > 0


@pytest.mark.parametrize("failure", [TimeoutError("timed out"), ConnectionResetError("reset"), urllib.error.URLError("no route"), http.client.IncompleteRead(b"")], ids=["timeout", "reset", "no route", "cut short"])
def test_no_answer_for_robots_txt_stops_the_run_with_a_clear_error(failure):
    client, site, _ = make({"/robots.txt": failure, "/page/one": PAGE_REPLY})
    with pytest.raises(FetchError, match="robots.txt of wiki.example.invalid could not be read"):
        client.get_text(PAGE, allow_page)
    assert set(site.paths) == {"/robots.txt"}


def test_a_robots_txt_that_has_moved_is_not_followed_and_stops_the_run():
    client, site, _ = make({"/robots.txt": text_reply("", status=301, headers={"Location": "https://elsewhere.example.invalid/robots.txt"}), "/page/one": PAGE_REPLY})
    with pytest.raises(FetchError, match="could not be read .*redirect refused"):
        client.get_text(PAGE, allow_page)
    assert site.paths == ["/robots.txt"]


def test_a_busy_robots_txt_keeps_its_retry_after():
    client, site, fake_time = make({"/robots.txt": [text_reply("", status=429, headers={"Retry-After": "7"}), text_reply(ALLOW_ALL)], "/page/one": PAGE_REPLY})
    assert client.get_text(PAGE, allow_page) == "<html>fine</html>"
    assert site.starts == [0.0, 7.0, 8.0] and fake_time.sleeps[0] == 7.0


def test_a_gzipped_robots_txt_is_read():
    client, site, _ = make({"/robots.txt": reply(body=b"User-agent: *\nDisallow: /page/\n", gz=True), "/page/one": PAGE_REPLY})
    with pytest.raises(FetchError, match="robots.txt does not allow"):
        client.get_text(PAGE, allow_page)


# ---- once for each host in a run -----------------------------------------------------------------------------------


def test_the_robots_txt_of_a_host_is_asked_for_once_in_a_run():
    routes = {SITE + "/robots.txt": text_reply(ALLOW_ALL), "/page/one": PAGE_REPLY, "/page/two": PAGE_REPLY}
    client, site, _ = make(routes)
    for path in ("/page/one", "/page/two", "/page/one", "/page/two"):
        client.get_text(SITE + path, allow_page)
    assert site.paths == ["/robots.txt", "/page/one", "/page/two", "/page/one", "/page/two"] and client.requests == 5


def test_each_host_has_its_own_robots_txt_asked_for_once_and_its_own_rules():
    routes = {
        SITE + "/robots.txt": text_reply(ALLOW_ALL),
        "https://other.example.invalid/robots.txt": text_reply("User-agent: *\nDisallow: /page\n"),
        SITE + "/page/one": PAGE_REPLY,
        "https://other.example.invalid/page": PAGE_REPLY,
    }
    client, site, _ = make(routes)
    client.get_text(PAGE, allow_page)
    for _ in range(2):
        with pytest.raises(FetchError, match="robots.txt does not allow"):
            client.get_text(OTHER, allow_page)
    client.get_text(PAGE, allow_page)
    assert [url for _when, url in site.calls] == [SITE + "/robots.txt", PAGE, "https://other.example.invalid/robots.txt", PAGE]


def test_the_api_is_asked_after_the_robots_txt_of_its_own_host_and_only_that_once():
    seen = []

    def transport(url, headers):
        seen.append(url)
        return text_reply(ALLOW_ALL) if url.endswith("/robots.txt") else reply({"query": {}})

    fake_time = FakeTime()
    client = PoliteClient(UA, transport=transport, clock=fake_time.clock, sleep=fake_time.sleep)
    client.get_json({"action": "query"})
    client.get_json({"action": "query"})
    assert seen[0] == "https://eqlwiki.com/robots.txt" and seen[1].startswith(API_URL + "?") and seen[2].startswith(API_URL + "?") and len(seen) == 3


def test_a_client_that_is_told_not_to_ask_robots_txt_does_not_and_the_default_is_to_ask():
    client, site, _ = make({"/page/one": PAGE_REPLY}, honour_robots=False)
    client.get_text(PAGE, allow_page)
    assert site.paths == ["/page/one"] and client.requests == 1
    assert PoliteClient(UA).honour_robots is True


# ---- the matching of a pattern is linear, the key of a host is its lower-cased name, and a long robots.txt is cut ----------------------------------------


def reference_allows(pattern: str, target: str) -> bool:
    """The meaning of a pattern, written the plain way for the tests (the oracle that the matcher is held to): RFC 9309's. ``*`` is any text, a ``$`` at the end anchors the pattern to the very end of the
    target, and it is matched at the start of the target. The matcher differs from the regular expression that it replaced (whose anchor was Python's ``$``) in ONE case: ``$`` also matched before a final
    newline, so ``/a$`` blocked ``/a%0A`` (unquoted to ``/a`` and a newline); the end here is ``\\Z``, the end of the text, which is the RFC's, and the matcher now allows that address."""
    text = urllib.parse.unquote(pattern)
    anchored = text.endswith("$")
    body = text[:-1] if anchored else text
    expression = ".*".join(re.escape(part) for part in body.split("*")) + (r"\Z" if anchored else "")
    return re.match(expression, urllib.parse.unquote(target), re.S) is not None


def test_a_pattern_with_many_stars_answers_in_milliseconds_where_a_backtracking_match_took_seconds():
    pattern = "/" + "*a" * 10 + "*b"  # ten stars: 12 seconds against the path below with a regular expression
    robots = parse_robots("User-agent: *\nDisallow: " + pattern, "trioforge-extractor")
    path = "/" + "a" * 39
    started = time.perf_counter()
    assert robots.allows(path) is True and robots.allows(path + "b") is False
    assert time.perf_counter() - started < 0.5
    started = time.perf_counter()
    many = parse_robots("User-agent: *\n" + "\n".join(f"Disallow: /{'*a' * 30}*b{n}" for n in range(200)), "trioforge-extractor")  # (as many rules as a long robots.txt has, thirty stars in each)
    assert many.allows("/" + "a" * 5000) is True
    assert time.perf_counter() - started < 5


@pytest.mark.parametrize("seed", range(6))
def test_the_matcher_agrees_with_the_plain_meaning_of_a_pattern_on_made_up_patterns_and_paths(seed):
    rng = random.Random(f"robots:{seed}")
    alphabet = ["a", "b", "/", "*", "$", "%2F", "%41", "?", "x", "a", "b", "%0A"]
    for _ in range(1500):
        pattern = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 9)))
        target = "".join(rng.choice(["a", "b", "/", "x", "?", "%41", "%2F", "$", "*", "%0A", "\n"]) for _ in range(rng.randint(0, 12)))
        robots = parse_robots("User-agent: *\nDisallow: " + pattern, "trioforge-extractor")
        assert robots.allows(target) is (not reference_allows(pattern, target) if pattern else True), (pattern, target)
    # and the rules that decide between two: the longest pattern, and Allow on a tie
    robots = parse_robots("User-agent: *\nDisallow: /a*c\nAllow: /a*b*c\nDisallow: /a*b*c$", "trioforge-extractor")
    assert [robots.allows(path) for path in ("/abc", "/abcx", "/ac", "/axbxc", "/axbxcd")] == [False, True, False, False, True]


@pytest.mark.parametrize("pattern,target,expected", [("/a*", "/", False), ("/a$", "/a", True), ("/a$", "/ab", False), ("/*$", "/x/y", True), ("*", "", True), ("/a*b$", "/ab", True), ("/a*b$", "/abb", True), ("/ab*b$", "/ab", False), ("/a*a$", "/a", False), ("/a$", "/a%0A", False), ("/*.php$", "/x.php%0A", False), ("/a*$", "/a\n", True), ("/a", "/a%0A", True)])
def test_the_edge_cases_of_a_pattern(pattern, target, expected):
    assert reference_allows(pattern, target) is expected
    robots = parse_robots("User-agent: *\nDisallow: " + pattern, "trioforge-extractor")
    assert robots.allows(target) is (not expected)


def test_the_robots_txt_of_a_host_is_asked_for_once_whatever_the_case_the_host_is_written_in():
    routes = {"/robots.txt": text_reply("User-agent: *\nDisallow: /secret/\n"), "/page/one": PAGE_REPLY, "/page/two": PAGE_REPLY}
    client, site, _ = make(routes)
    anywhere = lambda url: True  # (the allow function of a caller that holds its addresses to a list of its own: not what is tested)
    client.get_text("https://WIKI.Example.Invalid/page/one", anywhere)
    client.get_text(SITE + "/page/two", anywhere)
    with pytest.raises(FetchError, match="robots.txt does not allow"):
        client.get_text("https://wiki.EXAMPLE.invalid/secret/x", anywhere)
    assert site.paths == ["/robots.txt", "/page/one", "/page/two"] and client.requests == 3


def test_a_robots_txt_longer_than_the_limit_is_cut_at_it_and_read_not_refused():
    filler = "# " + "x" * 98 + "\n"
    head = "User-agent: *\nDisallow: /before/\n"
    tail = "Disallow: /after/\n"
    body = head + filler * (robots_module.MAX_ROBOTS_BYTES // len(filler) + 50) + tail
    assert len(body) > robots_module.MAX_ROBOTS_BYTES
    for gzipped in (False, True):
        client, site, _ = make({"/robots.txt": reply(body=body.encode(), gz=gzipped), "/before/x": PAGE_REPLY, "/after/x": PAGE_REPLY, "/other/x": PAGE_REPLY})
        with pytest.raises(FetchError, match="robots.txt does not allow"):
            client.get_text(SITE + "/before/x", allow_page)  # (the rule before the limit holds)
        assert client.get_text(SITE + "/after/x", allow_page) == "<html>fine</html>"  # (the rule after it was never read)
        assert client.get_text(SITE + "/other/x", allow_page) == "<html>fine</html>"


def a_body_whose_line_straddles_the_limit(head, line, kept, ending="\n"):
    """``head``, then comment lines, then ``line`` (and a line end) placed so that the limit falls inside it, after its first ``kept`` characters; returns the bytes. ``ending`` ends every line."""
    stop = ending.encode()
    comment = b"#" + b"x" * 99 + stop
    first = head.encode("utf-8")
    partial = len(line[:kept].encode("utf-8"))
    room = robots_module.MAX_ROBOTS_BYTES - len(first) - partial
    pad = room % len(comment)
    if pad < 1 + len(stop):
        pad += len(comment)
    body = first + comment * ((room - pad) // len(comment)) + b"#" + b"x" * (pad - 1 - len(stop)) + stop + line.encode("utf-8") + stop
    cut = body[: robots_module.MAX_ROBOTS_BYTES]
    assert len(body) > robots_module.MAX_ROBOTS_BYTES and len(cut) - 1 - max(cut.rfind(b"\n"), cut.rfind(b"\r")) == partial, "the limit falls inside the line, after `kept` characters of it"
    return body


@pytest.mark.parametrize("gzipped", [False, True], ids=["plain", "gzip"])
def test_an_allow_line_cut_short_by_the_limit_does_not_allow_a_path_that_the_whole_file_blocks(gzipped):
    """The partial last line is dropped: `Allow: /public/only-this-page` cut after `Allow: /pu` was read as a rule that allows everything under /pu, against a `Disallow: /` that the whole file has."""
    body = a_body_whose_line_straddles_the_limit("User-agent: *\nDisallow: /\n", "Allow: /public/only-this-page", len("Allow: /pu"))
    client, site, _ = make({"/robots.txt": reply(body=body, gz=gzipped), "/pub-secret/x": PAGE_REPLY, "/public/only-this-page": PAGE_REPLY})
    with pytest.raises(FetchError, match="robots.txt does not allow"):
        client.get_text(SITE + "/pub-secret/x", allow_page)
    assert site.paths == ["/robots.txt"], "nothing was asked of the page"


@pytest.mark.parametrize("gzipped", [False, True], ids=["plain", "gzip"])
@pytest.mark.parametrize("line,kept", [("Crawl-delay: 30", len("Crawl-delay: 3")), ("Crawl-delay: 120", len("Crawl-delay: 1"))])
def test_a_crawl_delay_cut_short_by_the_limit_is_not_used(gzipped, line, kept):
    """`Crawl-delay: 30` cut to `Crawl-delay: 3` made the client crawl ten times faster than asked, and a cut `Crawl-delay: 120` became 1 s where the whole file stops the run."""
    body = a_body_whose_line_straddles_the_limit("User-agent: *\nDisallow: /nothing-here/\n", line, kept)
    client, site, _ = make({"/robots.txt": reply(body=body, gz=gzipped), "/page/one": PAGE_REPLY})
    before = client.min_interval
    assert client.get_text(PAGE, allow_page) == "<html>fine</html>"
    assert client.min_interval == before, "no delay was taken from the line that the limit cut"


@pytest.mark.parametrize("line,kept", [("Crawl-delay: 30", len("Crawl-delay: 3")), ("Crawl-delay: 120", len("Crawl-delay: 1")), ("Allow: /public/only-this-page", len("Allow: /pu")), ("Disallow: /éééé", len("Disallow: /é") + 1)])
def test_what_is_kept_of_a_robots_txt_over_the_limit_ends_at_a_line_end_and_has_nothing_of_the_cut_line(line, kept):
    """The cut itself, whatever the line: it ends in a line end, it is under the limit, it has every whole line before the cut line and no part of it (a line with characters of more than one byte in it too)."""
    body = a_body_whose_line_straddles_the_limit("User-agent: *\nDisallow: /whole/\n", line, kept)
    kept_bytes = robots_module.limit_robots(body)
    assert kept_bytes.endswith(b"\n") and len(kept_bytes) < robots_module.MAX_ROBOTS_BYTES
    assert kept_bytes.startswith(b"User-agent: *\nDisallow: /whole/\n") and line[:kept].encode() not in kept_bytes
    assert robots_module.limit_robots(b"Disallow: /a\n") == b"Disallow: /a\n" and robots_module.limit_robots(b"x" * robots_module.MAX_ROBOTS_BYTES) == b"x" * robots_module.MAX_ROBOTS_BYTES
    assert robots_module.limit_robots(b"x" * (robots_module.MAX_ROBOTS_BYTES + 1)) == b""


@pytest.mark.parametrize("ending", ["\n", "\r", "\r\n"], ids=["lf", "cr", "crlf"])
def test_lines_that_end_before_the_limit_are_kept_whole_whatever_ends_them_and_the_line_the_limit_cuts_is_dropped(ending):
    head = "User-agent: *" + ending + "Disallow: /edge/" + ending
    body = a_body_whose_line_straddles_the_limit(head, "Disallow: /" + "y" * 40, len("Disallow: /y"), ending)
    client, site, _ = make({"/robots.txt": reply(body=body), "/edge/x": PAGE_REPLY, "/y/x": PAGE_REPLY})
    with pytest.raises(FetchError, match="robots.txt does not allow"):
        client.get_text(SITE + "/edge/x", allow_page)  # (a whole line before the limit holds, however it ends)
    assert client.get_text(SITE + "/y/x", allow_page) == "<html>fine</html>"  # (nothing of the cut line: a bare `Disallow: /y` would have blocked this)


def test_a_robots_txt_with_no_line_end_before_the_limit_reads_as_empty_not_as_a_partial_rule():
    body = b"Disallow: /" + b"z" * robots_module.MAX_ROBOTS_BYTES  # (one line, longer than the limit)
    client, site, _ = make({"/robots.txt": reply(body=body), "/page/one": PAGE_REPLY})
    assert client.get_text(PAGE, allow_page) == "<html>fine</html>"


def test_a_robots_txt_that_ends_exactly_at_the_limit_is_read_whole():
    head = b"User-agent: *\nDisallow: /last/"
    body = head + b"#" * (robots_module.MAX_ROBOTS_BYTES - len(head))  # (the last rule has no line end, and the file is not over the limit)
    assert len(body) == robots_module.MAX_ROBOTS_BYTES
    client, site, _ = make({"/robots.txt": reply(body=body), "/last/x": PAGE_REPLY})
    with pytest.raises(FetchError, match="robots.txt does not allow"):
        client.get_text(SITE + "/last/x", allow_page)


def test_a_robots_txt_of_the_size_of_a_real_one_is_read_whole():
    body = "User-agent: *\n" + "".join(f"Disallow: /private-{n}/\n" for n in range(2000)) + "Disallow: /last/\n"
    assert len(body) < robots_module.MAX_ROBOTS_BYTES
    client, site, _ = make({"/robots.txt": text_reply(body), "/last/x": PAGE_REPLY})
    with pytest.raises(FetchError, match="robots.txt does not allow"):
        client.get_text(SITE + "/last/x", allow_page)
