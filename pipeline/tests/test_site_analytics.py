"""Page counts as a setting of the build (Part J; reworked in Part M).

A build takes an optional analytics token (32 lower-case hex characters; Cloudflare Web Analytics). The pages carry NO script for the counter, in any build: a build with a token gives every page but
the 404 page the token as inert data (a <meta name="trioforge-counter"> in the head) and the header policy the two hosts of the counter; the page script adds the counter's script, once, to a page
that was opened with no kit link (counter.js; its rules are held by tests-js/counter.test.mjs and tests-e2e/analytics.spec.mjs). Without a token the build has no data, no host and no mark of a counter
in any page or header, and it is the same files as a counting build but for the token data, the About words and the policy line (the page script is one file for both builds: it does nothing without
the data). Every token here is invented: the real one is never in the repository.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from site_helpers import parse
from test_site_build import (  # noqa: F401  (site is a fixture of test_site_build: the plain build of the fixture, once for this module as well)
    CSP,
    NOT_FOUND,
    PAGES,
    header_blocks,
    need_node,
    read,
    run_build,
    site,
)

from trioforge.site import build

TOKEN = "0123456789abcdef0123456789abcdef"  # (invented)
OTHER_TOKEN = "fedcba9876543210fedcba9876543210"
VERIFICATION = "google0123456789abcdef.html"  # (invented)
# The ONE place where the invented values of the tests are declared. The scan of every tracked text file (test_the_token_and_the_file_name_are_in_no_tracked_text_file) allows these, wherever the
# tests of any language spell them, and nothing else: a 32-digit hex string with a letter in it, or a name of the shape of Google's file, that is not one of these fails the test. (The capitals and the
# short ones are the tests of the refusals; the JavaScript tests and playwright.config.mjs spell the first two.)
INVENTED_TOKENS = {TOKEN, OTHER_TOKEN, "abcdef0123456789abcdef0123456789"}
INVENTED_FILE_NAMES = {VERIFICATION, "googlefedcba9876543210.html", "googleabcdefabcdefabcd.html"}
META = '<meta name="trioforge-counter" content="' + TOKEN + '">'
OLD_TAG = '<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{"token": "' + TOKEN + "\"}'></script>"  # (Part J's tag: no page of any build has it now)
SCRIPT_HOST = "https://static.cloudflareinsights.com"
CONNECT_HOST = "https://cloudflareinsights.com"


def spy_on_the_command(monkeypatch):
    """The build is replaced by a function that records what the command gave it and stops, so the command line can be read without a build."""
    seen = []

    def stop(**kwargs):
        seen.append(kwargs)
        raise build.BuildError("stop here")

    monkeypatch.setattr(build, "build", stop)
    return seen


def html_files(out: Path):
    """The pages of a build (the Search Console file, which ends in .html as well, is none)."""
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*.html") if not p.name.startswith("google"))


def every_file(out: Path):
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())


@pytest.fixture(scope="module")
def counted(tmp_path_factory):
    """The build of the fixture with a token (the same results, the same options as the plain build of the fixture, indexable)."""
    need_node()
    tmp = tmp_path_factory.mktemp("site-counted")
    out = tmp / "dist"
    return out, run_build(out, tmp, analytics_token=TOKEN)


# ---- the token ---------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("token", [TOKEN, OTHER_TOKEN, "0" * 32, "f" * 32])
def test_a_token_is_32_lower_case_hex_characters(token):
    assert build.check_analytics_token(token) == token


@pytest.mark.parametrize(
    "token",
    ["", " ", TOKEN[:-1], TOKEN + "0", "g" * 32, TOKEN[:-1] + "g", " " + TOKEN, TOKEN + " ", TOKEN + "\n", TOKEN.upper(), "ABCDEF0123456789ABCDEF0123456789", TOKEN[:-1] + "A",
     "fedcba9876543210FEDCBA9876543210", "0123456789abcdef0123456789abcde'", "\"" + TOKEN[1:],
     "'" * 32, "0123456789abcdef0123456789abc<>f", TOKEN[:16] + "٠" * 16, "0123456789abcdef-123456789abcdef", None, 12345, b"0" * 32],
    ids=lambda value: repr(value)[:30],
)
def test_anything_else_is_refused_with_a_reason_that_does_not_repeat_it(token):
    with pytest.raises(build.BuildError, match="32 lower-case hex") as caught:
        build.check_analytics_token(token)
    if isinstance(token, str) and len(token) > 3:
        assert token not in str(caught.value)  # (what was given is not echoed into the message: it may be a pasted secret)


def test_a_bad_token_stops_the_build_before_anything_is_made(tmp_path):
    out = tmp_path / "dist"
    with pytest.raises(build.BuildError, match="32 lower-case hex"):
        run_build(out, tmp_path, analytics_token="not-a-token")
    assert not out.exists()
    with pytest.raises(build.BuildError, match="32 lower-case hex"):
        run_build(out, tmp_path, analytics_token=TOKEN.upper())  # (Cloudflare's tokens are lower case: a mistyped case would count nothing, silently)
    assert not out.exists()


def test_no_test_sees_the_build_settings_of_the_shell_it_is_run_from():
    """A maintainer sets the two settings in the shell to build a release (CONTRIBUTING suggests it), and the suite must not build counting sites, or write the Search Console file, because of it: the
    conftest clears both for every test. Shown here in a process of its own, with both set (a test that only looked at its own environment would pass in a clean shell for nothing)."""
    probe = Path(__file__).resolve().with_name("probe_build_settings.py")
    environment = {**os.environ, build.ANALYTICS_ENV: TOKEN, build.VERIFICATION_ENV: VERIFICATION, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-m", "pytest", str(probe), "-p", "no:cacheprovider"], env=environment, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, "a build setting of the shell reached a test"  # (the output is not shown: it could hold the shell's environment)


def test_a_preview_takes_no_token_from_the_environment_and_an_explicit_option_is_still_allowed(tmp_path, monkeypatch, capsys):
    """A build with --noindex is a preview, and a preview that counts says so with --analytics-token: the environment is where a release's setting lives, and a preview built by hand in a shell that holds
    it would have counted every visit without anyone asking."""
    seen = spy_on_the_command(monkeypatch)
    arguments = ["--results", str(tmp_path), "--out", str(tmp_path / "o"), "--noindex"]
    monkeypatch.setenv(build.ANALYTICS_ENV, OTHER_TOKEN)
    capsys.readouterr()
    assert build.main(arguments) == 2
    message = capsys.readouterr().err
    assert seen == [], "refused before a build is begun"
    assert "--noindex" in message and "--analytics-token" in message and build.ANALYTICS_ENV in message
    assert OTHER_TOKEN not in message, "the value is not echoed"
    assert build.main([*arguments, "--analytics-token", TOKEN]) == 2
    assert seen[-1]["analytics_token"] == TOKEN and seen[-1]["noindex"] is True, "an explicit option is allowed for a preview (the test preview of the browser tests)"
    monkeypatch.setenv(build.ANALYTICS_ENV, "")
    assert build.main(arguments) == 2 and seen[-1]["analytics_token"] is None, "an empty variable is no setting, for a preview too"
    monkeypatch.setenv(build.ANALYTICS_ENV, OTHER_TOKEN)
    assert build.main(arguments[:-1]) == 2 and seen[-1]["analytics_token"] == OTHER_TOKEN and seen[-1]["noindex"] is False, "an indexable build takes it from the environment, as before"


def test_the_command_takes_the_token_from_an_option_or_from_the_environment_and_refuses_a_bad_one(tmp_path, monkeypatch, capsys):
    seen = spy_on_the_command(monkeypatch)
    monkeypatch.delenv(build.ANALYTICS_ENV, raising=False)
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o")]) == 2
    assert seen[-1]["analytics_token"] is None  # (off by default)
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o"), "--analytics-token", TOKEN]) == 2
    assert seen[-1]["analytics_token"] == TOKEN
    monkeypatch.setenv(build.ANALYTICS_ENV, OTHER_TOKEN)
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o")]) == 2
    assert seen[-1]["analytics_token"] == OTHER_TOKEN
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o"), "--analytics-token", TOKEN]) == 2
    assert seen[-1]["analytics_token"] == TOKEN, "the option wins over the variable"
    monkeypatch.setenv(build.ANALYTICS_ENV, "")
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o")]) == 2
    assert seen[-1]["analytics_token"] is None, "an empty variable is no token"
    before = len(seen)
    monkeypatch.setenv(build.ANALYTICS_ENV, "zzznothexzzz")
    capsys.readouterr()
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o")]) == 2
    message = capsys.readouterr().err
    assert len(seen) == before and "32 lower-case hex" in message and "zzznothexzzz" not in message  # (refused before a build is begun, and the value is not echoed)
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o"), "--analytics-token", ""]) == 2
    assert len(seen) == before


# ---- the data and the policy ---------------------------------------------------------------------------------------------------------------------------


def test_the_data_is_exactly_the_one_meta_and_the_counter_has_one_address():
    assert build.counter_meta(TOKEN) == META
    assert build.ANALYTICS_SCRIPT_SRC == SCRIPT_HOST + "/beacon.min.js"
    assert build.COUNTER_META == "trioforge-counter"
    with pytest.raises(build.BuildError, match="32 lower-case hex"):
        build.counter_meta(TOKEN.upper())


def test_the_policy_of_a_counting_build_adds_exactly_the_two_hosts():
    plain = dict(part.strip().split(" ", 1) for part in CSP.split(";") if part.strip())
    counting = dict(part.strip().split(" ", 1) for part in build.ANALYTICS_CSP.split(";") if part.strip())
    assert list(counting) == list(plain), "the same directives in the same order"
    changed = {name for name in plain if plain[name] != counting[name]}
    assert changed == {"script-src", "connect-src"}
    assert counting["script-src"] == plain["script-src"] + " " + SCRIPT_HOST
    assert counting["connect-src"] == plain["connect-src"] + " " + CONNECT_HOST
    assert counting["trusted-types"] == plain["trusted-types"] == "trioforge" and counting["require-trusted-types-for"] == "'script'", "the Trusted Types directives are what they were"
    assert build.CSP == CSP, "the policy of the plain build is what it was"


def test_the_headers_of_a_counting_build_differ_from_the_plain_ones_in_the_policy_line_alone(site, counted):  # noqa: F811
    plain, _ = site
    out, _ = counted
    before, after = read(plain, "_headers"), read(out, "_headers")
    assert before != after
    assert before.replace(CSP, build.ANALYTICS_CSP) == after
    blocks = header_blocks(after)["/*"]
    assert blocks["Content-Security-Policy"] == build.ANALYTICS_CSP
    assert sorted(blocks) == ["Content-Security-Policy", "Permissions-Policy", "Referrer-Policy", "X-Content-Type-Options"]
    assert re.findall(r"https://[a-z.]+", after) == [SCRIPT_HOST, CONNECT_HOST], "the two hosts, and no other"


def test_the_committed_headers_file_is_still_the_plain_policy_and_is_refused_if_it_names_a_host():
    text = (Path(__file__).resolve().parents[2] / "site" / "_headers").read_text(encoding="utf-8")
    assert build.render_headers(text, noindex=False) == text
    assert build.render_headers(text, noindex=False, analytics=True) == text.replace(CSP, build.ANALYTICS_CSP)
    with pytest.raises(build.BuildError, match="exactly the Content-Security-Policy"):
        build.render_headers(text.replace(CSP, build.ANALYTICS_CSP), noindex=False)  # (the file in the repository carries no host: the build adds them)
    assert "cloudflare" not in text.lower()


# ---- the pages ------------------------------------------------------------------------------------------------------------------------------------


def test_no_page_of_a_counting_build_carries_a_script_for_the_counter_and_every_page_but_the_404_page_has_the_token_once_as_data(counted):
    out, summary = counted
    pages = html_files(out)
    assert NOT_FOUND in pages and pages == sorted(summary.pages)  # (every page the build made, 404.html among them)
    for name in pages:
        text = read(out, name)
        lowered = text.lower()
        scripts = re.findall(r"<script\b[^>]*>", text)
        assert len(scripts) == 2, f"{name}: the boot script and the page script, and no more"
        assert not any(marker in lowered for marker in build.BEACON_MARKERS), f"{name}: no mark of a beacon in the page"
        assert OLD_TAG not in text and TOKEN not in text.replace(META, ""), name
        if name == NOT_FOUND:
            assert build.COUNTER_META not in lowered, "the 404 page has no data for the counter"
            continue
        assert text.count(META) == 1 and lowered.count(build.COUNTER_META) == 1, name
        assert text.index(META) < text.index("</head>"), f"{name}: the data is in the head"
    assert any(p.startswith("trio/") for p in pages) and any(p.startswith("item/") for p in pages), "the trio pages and the item pages are among them"


def test_the_plain_build_has_no_beacon_no_data_no_marker_and_no_other_site_in_any_page_or_header(site):  # noqa: F811
    out, _ = site
    for name in html_files(out):
        text = read(out, name).lower()
        assert not any(marker in text for marker in build.BEACON_MARKERS), name
        assert build.COUNTER_META not in text, name
    assert "cloudflare" not in read(out, "_headers").lower()


def test_a_counting_build_is_the_plain_build_with_the_token_data_the_about_words_and_the_policy_added_and_nothing_else(site, counted):  # noqa: F811
    plain, _ = site
    out, _ = counted
    assert every_file(plain) == every_file(out), "the same files, the same hashed names"
    different = [name for name in every_file(plain) if (plain / name).read_bytes() != (out / name).read_bytes()]
    assert sorted(different) == sorted([*(n for n in html_files(plain) if n != NOT_FOUND), "_headers"])
    for name in html_files(plain):
        if name in (NOT_FOUND, "about/index.html"):
            continue
        before, after = read(plain, name), read(out, name)
        assert after.replace(META + "\n", "", 1) == before, name  # (one line more, in the head: the token as data)
        assert after.count(META + "\n") == 1
    about_plain, about_counted = read(plain, "about/index.html"), read(out, "about/index.html")
    assert about_counted.replace(META + "\n", "", 1).split("<h2>Privacy</h2>")[0] == about_plain.split("<h2>Privacy</h2>")[0], "the About page differs in the Privacy section alone"
    assert about_counted.split("<h2>Contact</h2>")[1] == about_plain.split("<h2>Contact</h2>")[1]
    assert (plain / NOT_FOUND).read_bytes() == (out / NOT_FOUND).read_bytes(), "the 404 page is the same bytes"
    for name in every_file(plain):
        if name.startswith(("assets/", "data/", "engine")):
            assert (plain / name).read_bytes() == (out / name).read_bytes(), name  # (no script, style or data of the site changes: ONE page script serves both builds, and does nothing without the data)


def test_the_page_script_is_one_file_for_both_builds_and_holds_the_counters_address_with_the_engine_client_and_no_other_asset(site, counted):  # noqa: F811
    plain, _ = site
    out, _ = counted
    holders = {}
    for root, label in ((plain, "plain"), (out, "counting")):
        holders[label] = sorted(p.relative_to(root).as_posix() for p in (root / "assets").rglob("*") if p.is_file() and b"cloudflareinsights" in p.read_bytes())
    assert holders["plain"] == holders["counting"]
    assert [re.sub(r"-[A-Z0-9]{8}", "-HASH", name) for name in holders["plain"]] == ["assets/app-HASH.js", "assets/engine/client-HASH.js"], "the two bundles that carry the policy (a name may be made once: they share the one record)"
    page_script = next(p for p in (plain / "assets").glob("app-*.js")).read_bytes()
    assert b"trioforge-counter" in page_script and b"data-cf-beacon" in page_script, "the code that adds the counter is in the page script of the plain build too: it does nothing without the data"


def test_nothing_in_any_page_of_a_counting_build_loads_from_another_site(counted):
    out, _ = counted
    loaded = set()
    for name in html_files(out):
        html = parse(read(out, name))
        for node in html.find_all():
            for attribute in ("src", "href", "action", "data", "poster", "srcset"):
                value = node.get(attribute)
                if not value or not re.match(r"(https?:)?//", value):
                    continue
                if node.tag == "a" or (node.tag == "link" and node.get("rel") == "canonical"):
                    continue  # (a link to follow, and an address for search engines: nothing is loaded)
                loaded.add((node.tag, value))
    assert loaded == set(), "the counter's script is added by the page script, to a page that may have it: no page names it"


# ---- the checks of the build -------------------------------------------------------------------------------------------------------------------------


def made_up(*, home_extra: bytes = b"", notfound_extra: bytes = b"", item_extra: bytes = b"", trio_extra: bytes = b"", head_extra: bytes = b""):
    """Made-up files for check_budgets and check_counter: a trio page, an item page, the home page and the 404 page."""
    css, boot, app, own = "assets/site-AAAAAAAA.css", "assets/boot-BBBBBBBB.js", "assets/app-CCCCCCCC.js", "assets/notfound-DDDDDDDD.js"
    meta = b'<meta http-equiv="Content-Security-Policy" content="' + build.NOTFOUND_POLICY.encode() + b'">'
    head = b'<link rel="stylesheet" href="/assets/site-AAAAAAAA.css"><script src="/assets/boot-BBBBBBBB.js"></script>'
    page = head + b'<script type="module" src="/assets/app-CCCCCCCC.js"></script>'
    files = {
        "index.html": b"<head>" + head_extra + b"</head>" + page + home_extra + b"</body>" + b"y" * 100,
        "404.html": meta + head + b'<script type="module" src="/assets/notfound-DDDDDDDD.js"></script>' + notfound_extra + b"z" * 100,
        "trio/pal-mnk-ber/index.html": b"<head>" + head_extra + b"</head>" + page + trio_extra + b"</body>",
        "item/w1/index.html": b"<head>" + head_extra + b"</head>" + page + item_extra + b"</body>",
        "about/index.html": b"<head>" + head_extra + b"</head>" + page + home_extra + b"</body>",
        css: b"a{}", boot: b"let b=2;", app: b"let a=1;", own: b"let n=3;",
    }
    first = {n: [css, boot, app] for n in ("index.html", "trio/pal-mnk-ber/index.html", "item/w1/index.html")}
    first["404.html"] = [css, boot, own]
    return files, first


def budget(files, first, **kwargs):
    return build.check_budgets(files, trio_pages=["trio/pal-mnk-ber/index.html"], first_load_assets=first, item_pages=["item/w1/index.html"], entry_pages={"home": "index.html", "notfound": "404.html"}, **kwargs)


def test_the_budgets_hold_every_page_to_two_scripts_in_every_build_a_beacon_tag_is_a_third_and_is_refused():
    files, first = made_up()
    budget(files, first)
    tag = OLD_TAG.encode()
    for where, extra, words in (
        ("home page index\\.html", {"home_extra": tag}, "the boot script and its own page script, 2"),
        ("item page item/w1/index\\.html", {"item_extra": tag}, "the boot script and the page script, 2"),
    ):
        with pytest.raises(build.BudgetError, match=where + r" has 3 scripts \(" + words + r"\)"):
            budget(*made_up(**extra))
    with pytest.raises(build.BudgetError, match=r"item page item/w1/index\.html has 3 scripts"):
        budget(*made_up(item_extra=b"<script>1</script>"))  # (any third script: a static one for the counter is no exception, since there is none)


def test_the_404_page_is_refused_a_beacon():
    files, first = made_up(notfound_extra=OLD_TAG.encode())
    with pytest.raises(build.BudgetError, match=r"404 page 404\.html carries an analytics beacon"):
        budget(files, first)


@pytest.mark.parametrize(
    "what,change,message",
    [
        ("none", lambda text: text.replace(META, ""), r"has 0 counter data"),
        ("two", lambda text: text.replace(META, META + META), r"has 2 counter data"),
        ("another token", lambda text: text.replace(TOKEN, OTHER_TOKEN), r"has 0 counter data"),
        ("the data after the head", lambda text: text.replace(META, "").replace("</head>", "</head>" + META), r"not in the head"),
        ("a beacon tag as well", lambda text: text.replace("</body>", OLD_TAG + "</body>"), r"carries an analytics beacon"),
        ("a mention of the beacon", lambda text: text.replace("</body>", "<!-- beacon.min.js --></body>"), r"carries an analytics beacon"),
    ],
)
def test_a_page_with_no_data_two_data_other_data_or_a_beacon_is_refused_naming_the_page(what, change, message):
    files, _ = made_up(head_extra=META.encode())
    pages = {name: text for name, text in files.items() if name.endswith(".html")}
    pages["trio/pal-mnk-ber/index.html"] = change(pages["trio/pal-mnk-ber/index.html"].decode()).encode()
    with pytest.raises(build.BuildError, match=r"trio/pal-mnk-ber/index\.html.*" + message):
        build.check_counter(pages, TOKEN)


def test_the_check_of_the_data_passes_a_counting_site_and_a_plain_one_and_refuses_data_where_there_is_no_token_or_on_the_404_page():
    files, _ = made_up(head_extra=META.encode())
    pages = {name: text for name, text in files.items() if name.endswith(".html")}
    build.check_counter(pages, TOKEN)
    with pytest.raises(build.BuildError, match=r"404\.html has counter data"):
        build.check_counter({**pages, "404.html": pages["404.html"] + META.encode()}, TOKEN)  # (the 404 page is the one page with none)
    plain, _ = made_up()
    build.check_counter({name: text for name, text in plain.items() if name.endswith(".html")}, None)
    with pytest.raises(build.BuildError, match=r"index\.html has counter data"):
        build.check_counter(pages, None)  # (a build with no token refuses data that it did not put there)


# ---- the about page ------------------------------------------------------------------------------------------------------------------------------


def privacy_text(out: Path) -> str:
    html = parse(read(out, PAGES["about"]))
    main = html.find("main")
    assert [h.text() for h in main.find_all("h2")] == ["What this is", "A fan project", "Privacy", "Contact"]
    paragraphs = main.find_all("p")
    start = next(i for i, p in enumerate(paragraphs) if p.text().lower().startswith("page counts are on"))
    return " ".join(p.text() for p in paragraphs[start : start + 3])  # (what is counted, the switches in the address, and what the site keeps in the browser)


def test_without_a_token_the_about_page_says_what_it_said(site):  # noqa: F811
    out, _ = site
    text = read(out, PAGES["about"])
    assert "TrioForge has no analytics. It sets no cookies, loads nothing from other sites and sends no information about you anywhere." in text
    assert "This preview" not in text, "the page is the site's, indexed or not"
    assert "When page counts are switched on later, they will be cookieless counts of page paths from Cloudflare Web Analytics" in text


def test_with_a_token_the_about_page_says_what_the_code_guarantees_and_attributes_the_rest_to_cloudflare(counted):
    out, _ = counted
    text = privacy_text(out)
    lowered = " ".join(text.lower().split())
    for words in (
        "page counts are on",
        "come from cloudflare web analytics",
        "a script from cloudflare, a third party",
        "runs in the page",
        "cloudflare describes it as cookieless",  # (said as Cloudflare's description, not as our own fact)
        "ip address",
        "details of your browser",
        "the address of the page",
        "the referrer",
        "your country",
        "kind of browser and device",
        "load timing",
        "a page that was opened from a shared kit link is not counted at all, and the script is not loaded there",
        "a shared kit link that you open in a tab that is already counted is in that tab's address for a moment before the page loads it again, and the script that is running there can see it",
        "the 404 page is not counted",
        "the switches you chose",
        "the site loads nothing else from other sites",
    ):
        assert words in lowered, words
    assert "theme button" in lowered and "light or dark choice" in lowered and "local storage" in lowered  # (the theme choice is one of the three things the site keeps: its sentence is in the paragraph after the counts)
    assert "only thing" not in lowered, "the site keeps three things in the browser, not one (the words are held by the table of what the static code stores)"
    assert "no analytics" not in lowered and "switched on later" not in lowered, "the words of the preview are gone"
    assert TOKEN not in read(out, PAGES["about"]).replace(META, ""), "the page does not print the token in words"


@pytest.mark.parametrize("promise", ["never holds it", "so a count never", "removed from the address before the count", "taken out of the address before the count", "keeps nothing in your browser", "sets no cookies and"])
def test_the_about_page_of_a_counting_build_promises_nothing_that_the_code_does_not_guarantee_or_that_is_cloudflares_to_say(counted, promise):
    out, _ = counted
    assert promise not in " ".join(read(out, PAGES["about"]).lower().split()), promise


def test_the_documents_a_visitor_can_read_make_no_promise_about_what_a_count_holds_that_the_code_cannot_keep():
    root = Path(__file__).resolve().parents[2]
    for path in (root / "docs" / "CHANGELOG.md", root / "pipeline" / "trioforge" / "site" / "templates" / "about.html.j2"):
        text = " ".join(path.read_text(encoding="utf-8").lower().split())
        for promise in ("never holds it", "before the count", "keeps nothing in your browser"):
            assert promise not in text, f"{path.name}: {promise}"
    decisions = " ".join((root / "docs" / "DECISIONS.md").read_text(encoding="utf-8").lower().split())
    assert "is no personal data" not in decisions, "DECISIONS states the owner's rule: kit codes are never counted"
    assert "kit codes are never counted" in decisions


def test_the_limits_of_what_the_design_cannot_do_are_said_in_decisions_and_in_the_comment_of_the_file_that_takes_the_kit():
    """P3: a running script cannot be unloaded, so a kit link pasted into a tab that is already counted is seen while the counter runs, until the page loads again; DECISIONS says so (the clean variant, the
    Navigation API's navigate and currententrychange events that come before popstate, pagehide, and the variant in which replaceState is refused); first.js's comment limits "a later listener finds a clean
    address" to popstate and hashchange."""
    root = Path(__file__).resolve().parents[2]
    decisions = " ".join((root / "docs" / "DECISIONS.md").read_text(encoding="utf-8").split())
    entry = decisions[decisions.index("- 2026-11-21 Part P:") :]
    for words in ("P3, what the design cannot do", "a running script cannot be unloaded", "already counted", "navigate", "currententrychange", "pagehide", "replaceState", "kept", "until the page loads again", "only for popstate and hashchange"):
        assert words in entry, words
    first = " ".join((root / "pipeline" / "trioforge" / "site" / "static" / "first.js").read_text(encoding="utf-8").replace("//", " ").split())
    assert "finds the address already clean" in first and "popstate and hashchange" in first and "not for the Navigation API's navigate and currententrychange" in first and "pagehide" in first
    assert "a script of the page that listens later, such as a counter that follows the history, finds the address already clean)" not in first, "the claim is not unqualified"


def test_the_reading_of_cloudflares_script_claims_no_more_than_the_reading_covers():
    """The architect's reading of js 2026.10.1 (K7) is background, not relied on, and says what it saw and what it did not: the sinks that were LOOKED FOR are listed, and not seeing them is not the script
    being known to run under `require-trusted-types-for 'script'` (the policy governs more sinks than the ones looked for); the address that is emptied before it is sent is the one of the first send."""
    root = Path(__file__).resolve().parents[2]
    decisions = " ".join((root / "docs" / "DECISIONS.md").read_text(encoding="utf-8").split())
    entry = decisions[decisions.index("Part K7 (docs only") : decisions.index("- 2026-11-20 Part M:")]
    runbook = " ".join((root / "docs" / "runbook-weekly.md").read_text(encoding="utf-8").split())
    for words in ("not seen in this reading", "sinks that were looked for", "createPolicy", "innerHTML", "document.write", "eval", "a script element made by code", "are not all the sinks",
                  "Function()", "setTimeout", "insertAdjacentHTML", "outerHTML", "DOMParser", "createContextualFragment", "srcdoc", "Worker", "importScripts", "first send", "does not say"):
        assert words in entry, words
    assert "none of the Trusted Types sinks" not in entry and "answered" not in entry, "the reading does not answer the Trusted Types question"
    assert "once, at its start" not in entry, "the address that is emptied is not claimed for every send"
    # the runbook says it in a few words, and no more than the entry does
    assert "no Trusted Types sink" not in runbook and "not seen in this reading" in runbook and "first send" in runbook


def test_the_runbook_and_contributing_say_that_the_dashboard_switch_stays_off_and_that_the_weekly_check_detects_it():
    """P1: the one-click switch of the Cloudflare dashboard puts a tag into every page at the edge, a counting site's policy would let it load, and nothing but this check could see it."""
    root = Path(__file__).resolve().parents[2]
    for name, path in (("runbook", root / "docs" / "runbook-weekly.md"), ("CONTRIBUTING", root / "CONTRIBUTING.md")):
        text = " ".join(path.read_text(encoding="utf-8").split())
        for words in ("Web Analytics switch of the Cloudflare dashboard", "must stay off", "the weekly check now detects it", "counting tag", "kit link"):
            assert words in text, (name, words)
    runbook = " ".join((root / "docs" / "runbook-weekly.md").read_text(encoding="utf-8").split())
    assert "with `--analytics` it also opens one trio page with an invented kit fragment" in runbook


def test_the_first_deploy_check_of_the_runbook_has_the_steps_that_can_find_a_leak_and_says_what_each_shows():
    """P7: step (1), the body of a page with no kit link, shows what the report holds and cannot show a kit; the steps that can are the kit link in a new tab (DevTools open BEFORE the link, the log
    preserved), a kit link pasted into an already counted tab (read what is sent afterwards, the one at pagehide included), and a kit page whose script is blocked followed by a link (what the clean page's
    navigation entries show, and what to expect of the network under the site's Referrer-Policy)."""
    root = Path(__file__).resolve().parents[2]
    runbook = " ".join((root / "docs" / "runbook-weekly.md").read_text(encoding="utf-8").split())
    for words in (
        "open DevTools in the new tab BEFORE the link is opened, and preserve the log",
        "it shows what the report holds",
        "cannot show a kit",
        "paste a kit link into the address bar of a tab that is already counted",
        "any later POST, the one at pagehide included",
        "block the page script",
        "app-*.js",
        "navigation.entries().map((entry) => entry.url)",
        "null",
        "If the console shows the address of the kit page, there must be NO request to either host",
    ):
        assert words in runbook, words


def test_contributing_names_the_spec_each_preview_is_for():
    root = Path(__file__).resolve().parents[2]
    text = " ".join((root / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    assert re.search(r"a second preview this way, on the port after `TRIOFORGE_PREVIEW_PORT` \(`TRIOFORGE_PREVIEW_EXALT_PORT` names another\), for `tests-e2e/exalt\.spec\.mjs` alone, and a third, the build with page counts, "
                     r"two ports after it \(`TRIOFORGE_PREVIEW_ANALYTICS_PORT` names another\), for `tests-e2e/analytics\.spec\.mjs` alone", text)


def test_the_runbook_names_the_check_that_can_see_a_leak_and_the_switch_that_the_weekly_task_needs_once_counts_are_live():
    root = Path(__file__).resolve().parents[2]
    runbook = " ".join((root / "docs" / "runbook-weekly.md").read_text(encoding="utf-8").split())
    contributing = " ".join((root / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    # the first-deploy check reads the request, not the dashboard (the dashboard shows paths: a fragment is not one, and the name of the navigation entry is shown nowhere)
    for words in ("cloudflareinsights.com/cdn-cgi/rum", "request body", "no request to either Cloudflare host", "--analytics", "The scheduled task's options change when page counts go live", "$options = '--indexable --analytics'"):
        assert words in runbook, words
    assert "for an address that holds" not in runbook and "look in the Web Analytics dashboard" not in runbook, "the step that cannot see the leak is gone"
    assert "--headers-file site/dist/_headers" not in contributing and "--headers-file <that folder>/_headers" not in runbook, "no instruction points at a build folder that the next build overwrites"
    assert "--analytics" in contributing
    # the reading of Cloudflare's script is background, said not to be relied on, in the runbook and in DECISIONS
    assert "not relied on" in runbook.lower()
    decisions = " ".join((root / "docs" / "DECISIONS.md").read_text(encoding="utf-8").split())
    assert "not relied on" in decisions.lower()


# ---- the token and the file name are never in the repository ---------------------------------------------------------------------------------------

# A scan in Python over every tracked file (not `git grep -o`, which resumes after a match and so missed a second token on a line after one separator, skipped a UTF-16 file as binary, and could not tell
# a dashed spelling): the 32 hex digits of a token with lookarounds (every run on a line is seen), the spelling with dashes (8-4-4-4-12, as an identifier is written), and the shape of Google's file name.
# NOT SEEN, and said (a test holds the list): a token split over lines, in base64, with \\u escapes or percent-encoded, or inside a longer run of hex digits (a hash of another kind); the history and the
# commit messages are the privacy scan's (its hook). Every file is read as its raw bytes and as UTF-16 and UTF-32 (see `decodings`): one stray NUL, a binary file or a UTF-32 file does not hide a value.
TOKEN_RUN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32}(?![0-9A-Fa-f])")
DASHED_RUN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])")
FILE_NAME_RUN = re.compile(r"google[0-9a-f]{16}\.html", re.IGNORECASE)
#: The fields of a release pointer (releases/*.json) that hold a 32-digit hex value and are no token: the random id of the release's snapshot (`secrets.token_hex(16)`). Nothing else under releases/ is let
#: through, and the shape of Google's file name is not let through anywhere.
RELEASE_ID_FIELDS = ("snapshot_id",)


def decodings(data: bytes) -> list[str]:
    """Every text that a file can be read as: its raw bytes (Latin-1, one character for each byte, so that a run of ASCII digits is a run whatever else the file holds: one stray NUL byte, a binary file,
    any other encoding of the text around it), and UTF-16 and UTF-32, little and big endian (PowerShell 5 writes UTF-16 for `>` and `Out-File`; a byte order mark is one character of the text and needs no
    case of its own, and the decoding of the other endianness finds nothing). A file is never skipped as binary: a run of 32 hex digits in a real binary file is as unlikely as it is in noise, and a
    value that a NUL byte hid from the scan is the case that mattered."""
    return [data.decode("latin-1"), *(data.decode(codec, "replace") for codec in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"))]


def found_in_tracked_text(root: Path, allowed_tokens: set[str], allowed_names: set[str]) -> list[tuple[str, int, str]]:
    """``(path, line, what)`` of every place in a tracked file (every folder, every language, every file: its raw bytes, and UTF-16 and UTF-32 of either endianness; see ``decodings``) that holds the 32 hex digits of a token (with a letter in them: a run of digits alone is a
    number, the fixtures hold some; the dashed spelling too) or the shape of Google's file name, and is not one of the invented values (compared in lower case, dashes left out). Under releases/ the one field
    of a pointer that holds such a value, RELEASE_ID_FIELDS, is let through, and nothing else. The values themselves are not returned: a real one must not be copied into the output of a test."""
    tokens = {name.lower() for name in allowed_tokens}
    names = {name.lower() for name in allowed_names}
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True, timeout=120).stdout.split(b"\0")
    places = []
    for raw in listed:
        if not raw:
            continue
        name = raw.decode("utf-8", "replace")
        try:
            data = (root / name).read_bytes()
        except OSError:
            continue
        for text in decodings(data):
            lines = text.split("\n")
            starts = [0]
            for line in lines[:-1]:
                starts.append(starts[-1] + len(line) + 1)
            for pattern, what in ((TOKEN_RUN, "token"), (DASHED_RUN, "token"), (FILE_NAME_RUN, "file name")):
                for found in pattern.finditer(text):
                    value = found.group(0).lower()
                    number = text.count("\n", 0, found.start()) + 1
                    if what == "token":
                        if not re.search(r"[a-f]", value):
                            continue
                        if value.replace("-", "") in tokens:
                            continue
                        line = lines[number - 1]
                        if name.startswith("releases/") and any(re.fullmatch(rf'\s*"{field}"\s*:\s*"[0-9a-f]{{32}}"\s*,?\s*', line) for field in RELEASE_ID_FIELDS):
                            continue
                    elif value in names:
                        continue
                    places.append((name, number, what))
    return sorted(set(places))


def tracked_repository() -> Path:
    root = Path(__file__).resolve().parents[2]
    try:
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available")
    if inside.returncode != 0:
        pytest.skip("not a git work tree")
    return root


def test_the_token_and_the_file_name_are_in_no_tracked_text_file_but_as_the_invented_ones_the_tests_declare():
    root = tracked_repository()
    assert found_in_tracked_text(root, INVENTED_TOKENS, INVENTED_FILE_NAMES) == [], "a token-shaped value or a Google file name in a tracked file that no test declares as invented (file, line, what: the value is not echoed)"


def test_the_scan_of_the_tracked_files_sees_a_real_looking_value_wherever_it_is_in_either_case_and_either_spelling_and_in_utf16(tmp_path):
    """The scan is shown to fail: in a repository of its own, a value in a script, a workflow, a package file, a note, an environment file, a document, a meta element, in lower and in upper case, as the
    second of two on one line, in a UTF-16 file (with and without a byte order mark), written with dashes, and in a release pointer outside the one field that may hold such a value, is found; the invented
    ones, a number, a run of 33 characters and the random id of a release are not."""
    run = lambda *arguments: subprocess.run(["git", *arguments], cwd=tmp_path, capture_output=True, text=True, check=True)  # noqa: E731
    run("init", "-q")
    real = "".join(["9f8e7d6c", "5b4a3928", "1706f5e4", "d3c2b1a0"])  # (in pieces: this file is scanned too, and must not hold what the scan looks for)
    real_name = "google" + "9f8e7d6c5b4a3928" + ".html"
    dashed = "-".join([real[:8], real[8:12], real[12:16], real[16:20], real[20:]])
    text_files = {
        "scripts/build.ps1": f'$env:TRIOFORGE_ANALYTICS_TOKEN = "{real}"\n',
        ".github/workflows/test.yml": f"  env:\n    TOKEN: {real.upper()}\n",
        "package.json": f'{{"config": {{"token": "{real}"}}}}\n',
        "notes/today.txt": f"the token is {real}.\n",
        ".env": f"TRIOFORGE_ANALYTICS_TOKEN={real}\n",
        "docs/page.md": f"<script data-cf-beacon='{{\"token\": \"{real}\"}}'></script>\nthe file is {real_name} and {real_name.upper()}\n",
        "meta.html": f'<meta name="trioforge-counter" content="{real}">\n',
        "two/on-a-line.txt": f"{TOKEN} {real}\n",  # (the invented one first, a single separator, the real one after it)
        "two/on-a-line-too.txt": f"{TOKEN}-{OTHER_TOKEN};{real}\n",
        "dashed/identifier.txt": f"id: {dashed}\n",
        "releases/data-2026-02-02.json": f'{{"snapshot_id": "{real}", "other": "{real}"}}\n',  # (the id on a line of its own is let through, a value anywhere else is not)
        "releases/data-2026-03-03.json": f'{{\n  "hash": "{real}"\n}}\n',
        "releases/data-2026-04-04.json": f'{{\n  "note": "{real_name}"\n}}\n',
    }
    for name, text in text_files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    for name, data in {
        "utf16/with-bom.txt": ("the token is " + real + "\r\n").encode("utf-16"),  # (what `Out-File` and `>` of Windows PowerShell 5 write)
        "utf16/le.txt": ("the token is " + real + "\r\n").encode("utf-16-le"),
        "utf16/be.txt": ("the token is " + real + "\r\n").encode("utf-16-be"),
        "utf16/name.txt": ("the file is " + real_name + "\r\n").encode("utf-16"),
    }.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    quiet = {
        "ok/invented.txt": f"{TOKEN} {OTHER_TOKEN.upper()} {VERIFICATION} {VERIFICATION.upper()}\n",
        "ok/invented-dashed.txt": "-".join([TOKEN[:8], TOKEN[8:12], TOKEN[12:16], TOKEN[16:20], TOKEN[20:]]) + "\n",
        "ok/number.json": '{"F": "14949008671791012111838758487691/50"}\n',
        "ok/longer.txt": f"{real}0 and 0{real} are 33 characters, a hash of another kind\n",
        "releases/data-2026-01-01.json": f'{{\n  "snapshot_id": "{real}",\n  "other": 1\n}}\n',
    }
    for name, text in quiet.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "ok" / "plain-binary.bin").write_bytes(b"\0\1\2\3\4" + b"\xff" * 40 + b"no run of hex digits of the length of a token here" + b"\0\0")  # (a binary file that holds none: nothing is found in it)
    (tmp_path / "found" / "binary.bin").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "found" / "binary.bin").write_bytes(b"\0\1\2" + real.encode("ascii") + b"\0\0")  # (a binary file that holds one: the raw bytes are searched since Part Q; it was left unread before)
    run("add", "-A")
    places = found_in_tracked_text(tmp_path, INVENTED_TOKENS, INVENTED_FILE_NAMES)
    tokens = sorted({path for path, _line, what in places if what == "token"})
    names = sorted({path for path, _line, what in places if what == "file name"})
    assert tokens == sorted(
        ["scripts/build.ps1", ".github/workflows/test.yml", "package.json", "notes/today.txt", ".env", "docs/page.md", "meta.html", "two/on-a-line.txt", "two/on-a-line-too.txt", "dashed/identifier.txt",
         "releases/data-2026-02-02.json", "releases/data-2026-03-03.json", "utf16/with-bom.txt", "utf16/le.txt", "utf16/be.txt", "found/binary.bin"]
    )
    assert names == sorted(["docs/page.md", "releases/data-2026-04-04.json", "utf16/name.txt"])
    assert ("releases/data-2026-02-02.json", 1, "token") in places, "the second value on the line of the release id is the one that is found"
    assert not any(real in str(place) or real_name in str(place) for place in places), "the places are paths and lines: the value is not echoed"


def test_the_scan_also_sees_a_value_that_one_stray_nul_a_utf32_file_or_mostly_non_ascii_utf16_text_hid_from_it(tmp_path):
    """The review's probe (Part Q, Q7): a text file with ONE NUL byte was taken for binary and not read; a UTF-32 file (with a byte order mark that begins like UTF-16 little endian's, or without) was not
    decoded; UTF-16 text that is mostly non-ASCII has too few NUL bytes to look like UTF-16. The scan now reads every file as its raw bytes (any run of the ASCII digits of a token is a run, whatever else is
    in the file) and as UTF-16 and UTF-32, little and big endian (a byte order mark needs no special case: the decoding of the other endianness finds nothing)."""
    run = lambda *arguments: subprocess.run(["git", *arguments], cwd=tmp_path, capture_output=True, text=True, check=True)  # noqa: E731
    run("init", "-q")
    real = "".join(["9f8e7d6c", "5b4a3928", "1706f5e4", "d3c2b1a0"])  # (in pieces: this file is scanned too)
    files = {
        "hidden/utf32-bom.txt": ("the token is " + real + "\n").encode("utf-32"),
        "hidden/utf32-le.txt": ("the token is " + real + "\n").encode("utf-32-le"),
        "hidden/utf32-be.txt": ("the token is " + real + "\n").encode("utf-32-be"),
        "hidden/one-nul.txt": ("the token is " + real + "\n\0\n").encode(),
        "hidden/utf16-cjk.txt": ("\u4e00" * 200 + real).encode("utf-16-le"),
        "hidden/utf16-cjk-be.txt": ("\u4e00" * 200 + real).encode("utf-16-be"),
        "hidden/utf16-bom-cjk.txt": ("\u4e00" * 200 + real).encode("utf-16"),
        "hidden/in-binary.dat": bytes(range(256)) * 4 + real.encode("ascii") + bytes(range(255, 0, -1)),
    }
    for name, data in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    quiet = {
        "quiet/utf32.txt": ("the token is not here, and these are numbers: 14949008671791012111838758487691\n").encode("utf-32"),
        "quiet/binary.dat": bytes(range(256)) * 8,
        "quiet/cjk.txt": ("\u4e00" * 300).encode("utf-16-le"),
    }
    for name, data in quiet.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    run("add", "-A")
    places = found_in_tracked_text(tmp_path, INVENTED_TOKENS, INVENTED_FILE_NAMES)
    assert sorted({path for path, _line, _what in places}) == sorted(files), "every one of the hidden values is found, and none of the quiet files is"
    assert not any(real in str(place) for place in places)


def test_the_scan_says_what_it_still_does_not_see(tmp_path):
    """What is NOT covered, held as a test so that it is said and a change shows: a token that is split over lines or written in base64, with \\u escapes or as percent-encoded text, or that stands inside a
    longer run of hex digits (a hash of another kind: the scan looks for runs of exactly 32). The history and the commit messages are the privacy scan's (its hook), not this test's."""
    run = lambda *arguments: subprocess.run(["git", *arguments], cwd=tmp_path, capture_output=True, text=True, check=True)  # noqa: E731
    run("init", "-q")
    real = "".join(["9f8e7d6c", "5b4a3928", "1706f5e4", "d3c2b1a0"])
    not_seen = {
        "split.txt": real[:16] + "\n" + real[16:] + "\n",
        "base64.txt": __import__("base64").b64encode(real.encode()).decode() + "\n",
        "escaped.json": '{"t": "' + "".join("\\u%04x" % ord(c) for c in real) + '"}\n',
        "percent.txt": "".join("%%%02x" % ord(c) for c in real) + "\n",
        "longer-run.txt": "deadbeef" + real + "\n",
    }
    for name, text in not_seen.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    run("add", "-A")
    assert found_in_tracked_text(tmp_path, INVENTED_TOKENS, INVENTED_FILE_NAMES) == []


# ---- what the About page says the site keeps in the browser, pinned to what the code keeps (Part L, L5) -----------------------------------------------------

STATIC = Path(__file__).resolve().parents[2] / "pipeline" / "trioforge" / "site" / "static"
#: every key the static code keeps in the browser: where, and the words the About page of both builds must have for it (lower case). A new stored thing is in this table
#: only when the About page says it, which the test below holds: the table is the place to add it, and the page the place to explain it.
STORED = {
    "trioforge-theme": ("localStorage", ("light or dark choice", "theme button", "local storage")),
    "trioforge-gear": ("localStorage", ("remember my gear on this device", "forget", "local storage")),
    "trioforge-engine-consent": ("sessionStorage", ("optimizer", "session storage", "for the browser session")),
}
#: the files of the static code that touch the browser's storage (a file that is not here and does is a new stored thing)
STORAGE_FILES = {"engine/client.js", "theme.js", "trio.js", "ui/remember.js"}
STORAGE_CALL = re.compile(
    r"""\.(?:getItem|setItem|removeItem)\(|\blocalStorage\b|\bsessionStorage\b|\[\s*["'`](?:getItem|setItem|removeItem|localStorage|sessionStorage)["'`]\s*\]|document\.cookie|\bindexedDB\b|\bcaches\.|\bserviceWorker\b|\bwindow\.name\b"""
)
#: the state that the static code puts in a history entry: a call of pushState or replaceState, by file, with the first argument as written. input/kitlocation.js keeps the kit of a shared link in
#: `history.state` (a reload shows it again; it goes with the entry), trio.js writes the address of the view and passes the state it finds through. A new call, or another argument, fails the test until it
#: is looked at and the About page says what it keeps.
HISTORY_STATE = {"input/kitlocation.js": "stateWith(history, payload)", "trio.js": "this.win.history.state"}
HISTORY_STATE_CALL = re.compile(r"""\.(?:pushState|replaceState)\(\s*((?:[^,()]|\([^()]*\))+?)\s*,""")  # (the first argument as written: a call with its own arguments is one argument)
#: the words that the About page of both builds must have for the kit that a tab's history entry keeps
HISTORY_WORDS = ("opened from a shared link", "tab's history", "a reload shows it again")
KEY_CONSTANT = re.compile(r"""\b[A-Z][A-Z_]*KEY\b\s*=\s*["']([^"']+)["']""")
KEY_LITERAL = re.compile(r"""\.(?:getItem|setItem|removeItem)\(\s*["']([^"']+)["']""")


def static_scripts() -> dict[str, str]:
    return {path.relative_to(STATIC).as_posix(): path.read_text(encoding="utf-8") for path in sorted(STATIC.rglob("*.js"))}


def test_the_table_of_what_the_site_keeps_in_the_browser_is_what_the_static_code_keeps():
    scripts = static_scripts()
    touching = {name for name, text in scripts.items() if STORAGE_CALL.search(text)}
    assert touching == STORAGE_FILES, "a script that touches the browser's storage is new (or no longer does): say what it keeps on the About page and in STORED"
    keys = {key for name in touching for key in (*KEY_CONSTANT.findall(scripts[name]), *KEY_LITERAL.findall(scripts[name]))}
    assert keys == set(STORED), "a key the code keeps is not in the table (or the table has one the code lost): the About page must say each"
    kinds = {kind for kind in ("localStorage", "sessionStorage") if any(kind in scripts[name] for name in touching)}
    assert kinds == {kind for kind, _ in STORED.values()}
    assert not [name for name, text in scripts.items() if re.search(r"document\.cookie|\bindexedDB\b|\bcaches\.|\bserviceWorker\b|\bwindow\.name\b", text)], "no cookie, database, cache, service worker or window name"


def test_the_pin_sees_bracket_access_to_the_storages_and_a_state_put_in_a_history_entry():
    for snippet in ['win["localStorage"].getItem(k)', "window['sessionStorage'].x", 'storage["setItem"]("a", "b")', "store['removeItem']('a')", "win[`localStorage`]", "window.name = x"]:
        assert STORAGE_CALL.search(snippet), snippet
    for snippet in ["const parsed = JSON.parse(text);", "map.get(key)", 'win.document.title = "x"', "history.length"]:
        assert not STORAGE_CALL.search(snippet), snippet
    assert [m.group(1) for m in HISTORY_STATE_CALL.finditer('history.replaceState(stateWith(history, payload), "", href); a.pushState({k: 1}, "")')] == ["stateWith(history, payload)", "{k: 1}"]


def test_the_table_of_what_the_site_puts_in_a_history_entry_is_what_the_static_code_does():
    found = {}
    for name, text in static_scripts().items():
        calls = [match.group(1) for match in HISTORY_STATE_CALL.finditer(text)]
        if calls:
            found[name] = calls
    assert found == {name: [first] for name, first in HISTORY_STATE.items()}, "a call of pushState or replaceState is new, or has another state: say what it keeps on the About page and in HISTORY_STATE"


def about_words(out: Path) -> str:
    return " ".join(parse(read(out, PAGES["about"])).find("main").text().lower().split())


@pytest.mark.parametrize("build_kind", ["plain", "counting"])
def test_the_about_page_of_both_builds_names_each_thing_the_site_keeps_and_says_none_of_it_is_sent(build_kind, request):
    out, _ = request.getfixturevalue("site" if build_kind == "plain" else "counted")
    text = about_words(out)
    for key, (kind, words) in STORED.items():
        for word in words:
            assert word in text, f"{key} ({kind}): the About page does not say {word!r}"
    assert "none of it is sent anywhere by the site" in text
    assert "this preview" not in text, "the page is the site's, indexed or not"
    assert text.count("local storage") >= 2 and text.count("session storage") >= 1
    for word in HISTORY_WORDS:
        assert word in text, f"history.state of input/kitlocation.js: the About page does not say {word!r}"
    assert "is gone when the history entry is" in text, "what the history entry keeps goes with it"
    assert "four things" in text and "three things" not in text, "the list names the fourth"
    assert "close the tab" not in text, "session storage is not promised to be cleared when the tab closes: a browser that restores its tabs may restore it"


def test_the_about_page_of_the_counting_build_says_the_counter_script_runs_in_the_page_of_the_remembered_gear(site, counted):  # noqa: F811
    assert "cloudflare's counter script runs in the same page as the remembered gear" in about_words(counted[0])
    assert "counter script" not in about_words(site[0])


def test_the_changelog_says_what_a_visitor_can_see_of_the_changes_of_parts_q_and_r():
    """The About page lists four things the site keeps, and a counting build counts fewer pages than it did (a link with a campaign parameter is not counted): a reader of the changelog is told, in the words of the page."""
    root = Path(__file__).resolve().parents[2]
    entries = [line for line in (root / "docs" / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if line.startswith("- 2026-11-21 ")]
    found = [line for line in entries if "four things" in line]
    assert len(found) == 1, "one entry says it"
    text = " ".join(found[0].lower().split())
    for words in ("light or dark choice", "remember", "optimizer", "browser session", "shared link", "history entry", "none of it is sent anywhere by the site", "campaign", "is not counted", "4,096 characters"):
        assert words in text, words
    for promise in ("never holds it", "keeps nothing in your browser", "only thing"):
        assert promise not in text, promise


def test_the_first_deploy_check_confirms_that_the_script_ran_and_that_one_report_went_to_the_data_host_and_says_what_a_failure_of_the_script_means():
    """R7: Cloudflare's current snippet loads its script as a module and ours is a classic script element (DECISIONS, R7). Nothing could be fetched to see whether the script needs the module form, so the
    first-deploy check says what to look at: the script ran (the element is in the page, the console has no error) and at least one request went to cloudflareinsights.com/cdn-cgi/rum (the real script may send
    more than one report, so the count that is seen is written down: S5); and what to do if not."""
    root = Path(__file__).resolve().parents[2]
    runbook = " ".join((root / "docs" / "runbook-weekly.md").read_text(encoding="utf-8").split())
    for words in (
        "confirm in DevTools that the script ran",
        "`script[data-cf-beacon]`",
        "no error in the console",
        "at least one request went to `cloudflareinsights.com/cdn-cgi/rum`",
        "write down how many you saw",
        "the number you wrote down in (1) does not grow",
        "`script.type = \"module\"`",
    ):
        assert words in runbook, words
    decisions = " ".join((root / "docs" / "DECISIONS.md").read_text(encoding="utf-8").split())
    assert "**R7, a classic script element, not a module" in decisions
    assert "exactly one request" not in runbook, "the real script was never seen: how many reports it sends is not known"
    # S5: where the module form comes from, what the classic form sends, and what changes with the one line
    for words in ("the install snippet that Cloudflare's dashboard showed the site owner on 2026-11-21", "classic scripts with `defer`", "credentials mode `include`", "the visitor's cookies for Cloudflare's host"):
        assert words in decisions, words
    assert "the tests holding as they are" not in decisions, "a test pins the classic element, so the tests do not hold as they are"
    assert "changes with it, which is what makes the change a decision" in decisions


def dated_entries_in_order(text: str) -> bool:
    """Whether the lines of a changelog that start with a date (``- YYYY-MM-DD ``) are in date order, oldest first."""
    dates = re.findall(r"^- (\d{4}-\d{2}-\d{2}) ", text, flags=re.MULTILINE)
    return dates == sorted(dates)


def test_the_changelog_lists_its_dated_entries_in_date_order():
    """S5: the 2026-11-21 entry sat before the last of 2026-11-20."""
    root = Path(__file__).resolve().parents[2]
    assert dated_entries_in_order((root / "docs" / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert not dated_entries_in_order("- 2026-11-21 a\n- 2026-11-20 b\n"), "the check can fail"
    assert dated_entries_in_order("- 2026-11-20 a\n- 2026-11-20 b\n- 2026-11-21 c\n")
