"""The 404 page: a real 404 with a neutral title, a small script of its own, the list of trios that script canonicalizes against, and the guards that keep an analytics beacon and the
code that takes a kit link out of the address away from it.

Cloudflare Pages answers an address it has no file for with ``404.html`` and a 404 (see ``test_site_build.py``). The page is the same for every such address, so it cannot name one. Its
script moves a visitor who typed a trio in another order, case or form to the page of the trio (tests-js/canonical.test.mjs and tests-js/notfound.test.mjs hold the rules, tests-e2e/
canonical.spec.mjs the browser), and the page has to deliver the kit link of its address to that page untouched: it must therefore not run the code that takes it out, and it must not carry a
beacon, which would see it. The build holds both of those to the files, since a convention would not survive the next edit.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from site_helpers import parse
from test_site_build import (
    CSP,
    MANIFEST,
    NOT_FOUND,
    PAGES,
    RESULTS,
    TEMPLATES,
    header_blocks,
    need_node,
    page,
    read,
    run_build,
    site,  # noqa: F401  (a fixture of test_site_build: the build of the fixture, once for this module as well)
)
from test_site_home import FIVE, every_trio, five, stub_page, trios_made_of  # noqa: F401  (five is a fixture)

from trioforge.site import build

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "pipeline" / "trioforge" / "site" / "static"
#: the markers of Cloudflare's analytics beacon: the host it is loaded from, the script's name and the attribute that carries its token
BEACON_MARKERS = ("cloudflareinsights", "beacon.min.js", "data-cf-beacon")
#: what the 404 page says of itself, in a meta element: a policy that a page gives adds to the header's, so nothing on this page, whoever put it there, can load a script of another site or send anything
POLICY = "script-src 'self'; connect-src 'none'"
META = f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">'


def notfound_html(slugs: list[str]) -> str:
    return stub_page("notfound.html.j2", **build.notfound_context(trios_made_of(slugs)))


# ---- the page: a neutral title, the frame, the list -----------------------------------------------------------------------------------------------


def test_the_404_page_has_a_neutral_title_that_names_no_address_and_no_canonical_link(site):  # noqa: F811
    out, _ = site
    html = page(out, NOT_FOUND)
    assert html.find("title").text() == "Page not found · TrioForge"
    assert html.find_all("link", rel="canonical") == []  # (it is shown at whatever address was asked for)
    assert [h.text() for h in html.find_all("h1")] == ["Page not found"]
    description = html.find("meta", name="description").get("content")
    assert "home page" in description and "/" not in description  # (it names no address)
    # the same page is sent for every address that has no file, so a preview of a link that the script would move shows these words, whatever the link was
    assert html.find("main").get("data-page") == "notfound"


def test_the_404_page_carries_the_list_of_the_trios_of_the_build_in_one_attribute(five):
    html = page(five.out, NOT_FOUND)
    listed = html.find("main").get("data-trios")
    assert listed == " ".join(FIVE)
    assert re.fullmatch(r"[a-z]{3}-[a-z]{3}-[a-z]{3}( [a-z]{3}-[a-z]{3}-[a-z]{3})*", listed)
    # the page names the five of them, and all five open
    hrefs = [a.get("href") for a in html.find("main").find_all("a")]
    assert hrefs[0] == "/"
    assert [h for h in hrefs if h.startswith("/trio/")] == [f"/trio/{slug}/" for slug in FIVE]


def test_the_404_page_of_the_full_grid_lists_no_trio_in_the_page_but_carries_the_list_for_the_script():
    html = parse(notfound_html(every_trio()))
    main = html.find("main")
    assert main.get("data-trios").split(" ") == every_trio()
    assert [a.get("href") for a in main.find_all("a")] == ["/"], "560 links in a page that is sent for every wrong address would weigh as much as the home page"
    assert main.find_all("h2") == []
    assert len(notfound_html(every_trio()).encode("utf-8")) <= build.LIMITS["notfound_html"]
    # up to the number that is listed, the links are there
    few = parse(notfound_html(every_trio()[: build.NOT_FOUND_LISTED])).find("main")
    assert len([a for a in few.find_all("a") if a.get("href").startswith("/trio/")]) == build.NOT_FOUND_LISTED
    more = parse(notfound_html(every_trio()[: build.NOT_FOUND_LISTED + 1])).find("main")
    assert [a for a in more.find_all("a") if a.get("href").startswith("/trio/")] == []


def test_the_404_page_has_a_place_for_a_hint_that_is_empty_and_hidden_and_has_no_link(site):  # noqa: F811
    out, _ = site
    hint = page(out, NOT_FOUND).by_id("notfound-hint")
    assert hint.has("hidden") and hint.text() == "" and hint.find_all("a") == []
    # the links that the page has in its own markup all lead to a page of the site (the search link is made by the script, for the addresses it is useful at)
    for a in page(out, NOT_FOUND).find("main").find_all("a"):
        assert (out / (a.get("href").lstrip("/") + "index.html")).is_file()


def test_the_404_page_is_not_in_the_sitemap_and_robots_say_nothing_of_it(site):  # noqa: F811
    out, _ = site
    assert "404" not in read(out, "sitemap.xml") and "404" not in read(out, "robots.txt")


# ---- its own script ----------------------------------------------------------------------------------------------------------------------------------


def test_the_404_page_loads_the_boot_script_and_a_script_of_its_own_and_not_the_page_script(site):  # noqa: F811
    out, _ = site
    html = page(out, NOT_FOUND)
    scripts = html.find_all("script")
    assert [(s.get("src").split("-")[0], s.get("type")) for s in scripts] == [("/assets/boot", None), ("/assets/notfound", "module")]
    assert scripts[0] in html.find("head").children and scripts[1] in html.find("body").children
    assert len(html.find_all("link", rel="stylesheet")) == 1
    files = sorted(p.name for p in (out / "assets").iterdir() if p.is_file())
    assert [n for n in files if re.fullmatch(r"notfound-[A-Z0-9]{8}\.js", n)], files
    assert scripts[1].get("src") == "/assets/" + next(n for n in files if n.startswith("notfound-"))
    # and no other page loads it
    for key, name in PAGES.items():
        assert "/assets/notfound" not in read(out, name), key


def test_the_frame_keeps_the_page_script_in_a_block_that_the_404_page_replaces_whole():
    base = (TEMPLATES / "base.html.j2").read_text(encoding="utf-8")
    notfound = (TEMPLATES / "notfound.html.j2").read_text(encoding="utf-8")
    assert re.search(r'{% block page_script %}\s*<script type="module" src="{{ assets\.app }}"></script>\s*{% endblock %}', base)
    assert re.search(r'{% block page_script %}\s*<script type="module" src="{{ assets\.notfound }}"></script>\s*{% endblock %}', notfound)
    assert "assets.app" not in notfound, "the 404 page has no part of the page script"
    # the one place for a script that is not the frame's: nothing else in the frame loads one after the block
    assert base.index("{% endblock %}", base.index("{% block page_script %}")) < base.index("</body>")
    assert len(re.findall(r"<script\b", base)) == 2  # the boot script in the head, and the page script in the block


def test_the_script_of_the_404_page_is_one_file_that_imports_nothing(site):  # noqa: F811
    out, _ = site
    script = next((out / "assets").glob("notfound-*.js")).read_text(encoding="utf-8")
    assert not re.search(r"""(?<![\w$.])import\s*[{*"'\w$(]""", script), "no static or dynamic import: one request"
    assert "trioforge-theme" in script  # the theme button works on the page, with the same key as the other pages
    assert len(script.encode("utf-8")) < 6 * 1024, "a small script"


def test_the_script_of_the_404_page_has_no_code_that_takes_a_kit_link_out_of_the_address(site):  # noqa: F811
    out, _ = site
    script = next((out / "assets").glob("notfound-*.js")).read_text(encoding="utf-8")
    for piece in ("replaceState", "kitFragment", "#k=", "pushState", "sendBeacon", "XMLHttpRequest", "fetch(", "localStorage.setItem"):
        assert piece not in script, piece
    app = next((out / "assets").glob("app-*.js")).read_text(encoding="utf-8")
    assert "replaceState" in app and "kitFragment" in app  # (the control: this is what the page script has, and the 404 page must not)


def test_the_bundle_of_the_404_script_is_made_of_its_own_three_files_and_nothing_else(site):  # noqa: F811
    need_node()
    meta: dict = {}
    build.bundle_assets(keep_notfound_metafile=meta)
    outputs = {name: info for name, info in meta["outputs"].items() if name.endswith(".js")}
    assert len(outputs) == 1
    (info,) = outputs.values()
    held = sorted(Path(name.replace("\\", "/")).name for name in info["inputs"])
    assert held == sorted(build.NOTFOUND_INPUTS) == ["canonical.js", "notfound.js", "theme.js"]
    assert info.get("imports", []) == [], "nothing is loaded after it"


def test_a_404_bundle_that_holds_the_fragment_guard_or_the_page_code_is_refused():
    def bundle(*inputs: str) -> dict:
        return {"outputs": {"out/notfound-AAAAAAAA.js": {"entryPoint": "notfound.js", "imports": [], "inputs": {name: {"bytesInOutput": 10} for name in inputs}}}}

    own = ("notfound.js", "canonical.js", "theme.js")
    build.check_notfound_script(bundle(*own))
    build.check_notfound_script(bundle(*[f"pipeline/trioforge/site/static/{name}" for name in own]))  # (named from the root of the repository)
    for extra, name in (("first.js", "first.js"), ("input/kitlocation.js", "kitlocation.js"), ("trio.js", "trio.js"), ("picker.js", "picker.js"), ("ui/share.js", "share.js")):
        with pytest.raises(build.BuildError, match=rf"{re.escape(name)}.*(404|fragment|kit)"):
            build.check_notfound_script(bundle(*own, extra))
    with pytest.raises(build.BuildError, match="no script"):
        build.check_notfound_script({"outputs": {}})
    with pytest.raises(build.BuildError, match="imports"):
        meta = bundle(*own)
        meta["outputs"]["out/notfound-AAAAAAAA.js"]["imports"] = [{"path": "chunk-BBBBBBBB.js", "kind": "import-statement"}]
        build.check_notfound_script(meta)


def test_a_404_bundle_that_lacks_one_of_its_three_files_is_refused():
    def bundle(*inputs: str) -> dict:
        return {"outputs": {"out/notfound-AAAAAAAA.js": {"entryPoint": "notfound.js", "imports": [], "inputs": {name: {"bytesInOutput": 10} for name in inputs}}}}

    own = ("notfound.js", "canonical.js", "theme.js")
    build.check_notfound_script(bundle(*own))
    for missing in own:
        with pytest.raises(build.BuildError, match=rf"does not hold {re.escape(missing)}"):
            build.check_notfound_script(bundle(*[name for name in own if name != missing]))
    with pytest.raises(build.BuildError, match="does not hold"):
        build.check_notfound_script(bundle())


def test_a_notfound_script_that_drops_its_import_of_the_canonicalizer_is_refused_by_the_build(tmp_path, monkeypatch):
    """The script that would canonicalize nothing: in a copy of the page code, notfound.js has stubs where it imports canonical.js, so the bundle is made, holds two of its three files, and
    would ship a 404 page that moves no one."""
    need_node()
    copy = tmp_path / "static"
    shutil.copytree(STATIC, copy)
    monkeypatch.setattr(build, "STATIC", copy)
    meta = build._bundle_notfound(tmp_path / "control")  # (the control: the page code as it is is made into the bundle, which holds its three files)
    assert sorted(Path(name).name for info in meta["outputs"].values() for name in info.get("inputs", {})) == ["canonical.js", "notfound.js", "theme.js"]
    source = (copy / "notfound.js").read_text(encoding="utf-8")
    line = 'import { areaOf, canonicalUrl, isSafeTarget } from "./canonical.js";'
    assert line in source
    stubs = ["const areaOf = () => null;", "const canonicalUrl = () => null;", "const isSafeTarget = () => false;"]
    (copy / "notfound.js").write_text(source.replace(line, "\n".join(stubs)), encoding="utf-8")
    with pytest.raises(build.BuildError, match=r"does not hold canonical\.js"):
        build._bundle_notfound(tmp_path / "stubbed")


def test_the_404_script_of_the_build_is_checked_when_the_assets_are_bundled(monkeypatch):
    need_node()
    seen = []
    real = build.check_notfound_script
    monkeypatch.setattr(build, "check_notfound_script", lambda meta: (seen.append(meta), real(meta))[1])
    build.bundle_assets()
    assert len(seen) == 1 and "outputs" in seen[0]


# ---- no beacon ---------------------------------------------------------------------------------------------------------------------------------------


def test_the_404_page_has_no_beacon_no_foreign_script_and_the_policy_names_no_analytics_host(site):  # noqa: F811
    out, _ = site
    text = read(out, NOT_FOUND)
    for marker in BEACON_MARKERS:
        assert marker not in text.lower(), marker
    html = parse(text)
    assert all(s.get("src").startswith("/assets/") for s in html.find_all("script"))
    for node in [*html.find_all("script"), *html.find_all("link")]:
        loaded = node.get("src") or node.get("href") or ""
        assert loaded.startswith(("/", "data:")), loaded  # (an address for search engines is none of these, and the page has none)
    assert html.find_all("iframe") == [] and html.find_all("img") == [] and html.find_all("object") == []
    policy = header_blocks(read(out, "_headers"))["/*"]["Content-Security-Policy"]
    assert policy == CSP == build.CSP and "cloudflare" not in policy.lower()


def test_the_404_page_carries_a_policy_of_its_own_before_anything_that_loads_and_no_other_page_does(site):  # noqa: F811
    out, _ = site
    text = read(out, NOT_FOUND)
    html = parse(text)
    metas = [m for m in html.find_all("meta") if (m.get("http-equiv") or "").lower() == "content-security-policy"]
    assert len(metas) == 1 and metas[0].get("content") == POLICY == build.NOTFOUND_POLICY
    assert metas[0] in html.find("head").children
    assert text.index('http-equiv="Content-Security-Policy"') < min(text.index("<link"), text.index("<script")), "it comes before the stylesheet and the scripts, which it governs"
    for key, name in PAGES.items():
        assert "http-equiv" not in read(out, name).lower(), key  # (the header is the policy of every other page)


def test_the_policy_of_the_404_page_lets_no_script_come_but_its_own_and_no_connection_go():
    directives = dict(part.strip().split(" ", 1) for part in build.NOTFOUND_POLICY.split(";") if part.strip())
    assert directives == {"script-src": "'self'", "connect-src": "'none'"}
    assert "unsafe" not in build.NOTFOUND_POLICY and "*" not in build.NOTFOUND_POLICY and "http" not in build.NOTFOUND_POLICY
    # the page code of the 404 page asks for nothing: no fetch, no beacon, no storage written (see the test of its script), so a policy of none costs it nothing
    assert "<meta" in notfound_html(["pal-mnk-ber"]) and POLICY in notfound_html(["pal-mnk-ber"])


def test_a_404_page_without_the_policy_or_with_another_or_late_is_refused_naming_the_page():
    files, first = first_load_files()
    check(files, first)  # (the control: the made-up page has its policy first)
    original = files["404.html"]
    other = "script-src 'self' https://static.cloudflareinsights.com; connect-src 'none'"
    for broken, why in (
        (original.replace(META.encode(), b""), "none"),
        (original.replace(POLICY.encode(), other.encode()), "a policy that lets a script of another site come"),
        (original.replace(POLICY.encode(), b"script-src 'self'; connect-src 'self'"), "a policy that lets the page connect"),
        (original.replace(POLICY.encode(), b"script-src 'self'"), "a policy with no connect-src"),
        (original.replace(META.encode(), b"") + META.encode(), "a policy after everything that loads"),
        (original.replace(META.encode(), META.encode() + META.encode()), "two policies"),
        (original.replace(META.encode(), b'<meta http-equiv="Content-Security-Policy-Report-Only" content="' + POLICY.encode() + b'">'), "a report-only policy, which enforces nothing"),
        (original.replace(b'http-equiv="Content-Security-Policy"', b'name="Content-Security-Policy"'), "a meta that is not an http-equiv one"),
    ):
        try:
            check({**files, "404.html": broken}, first)
        except build.BudgetError as error:
            assert re.search(r"404 page 404\.html [^;]*polic", str(error)), f"{why}: the message does not name the page and the policy: {error}"
        else:
            pytest.fail(f"a 404 page with {why} was not refused")
    # a policy written in capitals is the same policy
    assert check({**files, "404.html": original.replace(b"Content-Security-Policy", b"content-security-policy")}, first)["notfound_html"]


def first_load_files(*, extra_notfound: bytes = b"", extra_home: bytes = b"", home_size: int = 100, notfound_size: int = 100):
    """Made-up files for check_budgets: the home page, the 404 page, and the three files each loads."""
    css, boot, app, own = "assets/site-AAAAAAAA.css", "assets/boot-BBBBBBBB.js", "assets/app-CCCCCCCC.js", "assets/notfound-DDDDDDDD.js"
    head = b'<link rel="stylesheet" href="/assets/site-AAAAAAAA.css"><script src="/assets/boot-BBBBBBBB.js"></script>'
    files = {
        "index.html": head + b'<script type="module" src="/assets/app-CCCCCCCC.js"></script>' + extra_home + b"y" * home_size,
        "404.html": META.encode() + head + b'<script type="module" src="/assets/notfound-DDDDDDDD.js"></script>' + extra_notfound + b"z" * notfound_size,
        css: b"a{}",
        boot: b"let b=2;",
        app: b"let a=1;",
        own: b"let n=3;",
        "trio/pal-mnk-ber/index.html": b"<html></html>",
    }
    first = {"index.html": [css, boot, app], "404.html": [css, boot, own], "trio/pal-mnk-ber/index.html": [css, boot, app]}
    return files, first


def check(files, first):
    return build.check_budgets(files, trio_pages=["trio/pal-mnk-ber/index.html"], first_load_assets=first, entry_pages={"home": "index.html", "notfound": "404.html"})


def test_the_budget_check_measures_the_home_page_and_the_404_page_and_counts_the_script_of_the_404_page_as_a_first_load():
    files, first = first_load_files(home_size=3000, notfound_size=2000)
    sizes = check(files, first)
    assert sizes["home_html"] == len(files["index.html"]) and sizes["notfound_html"] == len(files["404.html"])
    assert 0 < sizes["home_html_gzip"] < sizes["home_html"] and 0 < sizes["notfound_html_gzip"] < sizes["notfound_html"]
    assert sizes["home_first_load_gzip"] > sizes["home_html_gzip"] and sizes["notfound_first_load_gzip"] > sizes["notfound_html_gzip"]
    assert sizes["total_js"] == len(files["assets/app-CCCCCCCC.js"]) + len(files["assets/boot-BBBBBBBB.js"]) + len(files["assets/notfound-DDDDDDDD.js"])
    assert sizes["lazy_js"] == 0, "the script of the 404 page is not code that is loaded on first use"


def test_a_404_page_that_carries_a_beacon_is_refused_naming_the_page_and_the_beacon():
    for beacon in (
        b'<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{"token": "x"}\'></script>',
        b'<script defer src="/assets/beacon.min.js"></script>',
        b'<div data-cf-beacon="1"></div>',
        b"<p>cloudflareinsights</p>",
    ):
        files, first = first_load_files(extra_notfound=beacon)
        with pytest.raises(build.BudgetError, match=r"404 page 404\.html carries an analytics beacon"):
            check(files, first)


def test_a_script_added_to_the_home_page_is_refused_like_one_added_to_any_page_that_has_two():
    files, first = first_load_files(extra_home=b'<script defer src="https://static.cloudflareinsights.com/beacon.min.js"></script>')
    with pytest.raises(build.BudgetError, match=r"home page index\.html has 3 scripts"):
        check(files, first)  # (a build that adds the beacon to the pages that may have one changes this number on purpose; the 404 page's answer is the next test)


def test_a_404_page_that_loads_the_page_script_or_another_script_is_refused():
    files, first = first_load_files(extra_notfound=b'<script type="module" src="/assets/app-CCCCCCCC.js"></script>')
    with pytest.raises(build.BudgetError, match=r"404 page 404\.html loads /assets/app-CCCCCCCC\.js, which is not part of its first load"):
        check(files, first)
    files, first = first_load_files(extra_notfound=b"<script>alert(1)</script>")
    with pytest.raises(build.BudgetError, match=r"404 page 404\.html has 3 scripts"):
        check(files, first)
    files, first = first_load_files()
    files["404.html"] = files["404.html"].replace(b"/assets/notfound-DDDDDDDD.js", b"/assets/app-CCCCCCCC.js")
    with pytest.raises(build.BudgetError, match=r"404 page 404\.html (loads|does not load)"):
        check(files, first)


def test_the_pages_are_held_to_their_own_limits_and_the_first_load_of_every_page_and_the_message_names_the_page():
    limits = build.LIMITS
    assert (limits["notfound_html"], limits["notfound_html_gzip"]) == (16 * 1024, 5 * 1024)
    files, first = first_load_files(notfound_size=limits["notfound_html"])
    with pytest.raises(build.BudgetError, match=r"404 page 404\.html is 16\.\d KB \(limit 16 KB\)"):
        check(files, first)
    files, first = first_load_files(home_size=limits["home_html"])
    with pytest.raises(build.BudgetError, match=r"home page index\.html is 80\.\d KB \(limit 80 KB\)"):
        check(files, first)
    # gzip: bytes that do not compress
    import os

    files, first = first_load_files()
    files["404.html"] += os.urandom(6 * 1024)
    with pytest.raises(build.BudgetError, match=r"404 page 404\.html is \d\.\d KB gzip \(limit 5 KB\)"):
        check(files, first)
    # the first load of a page, whatever is in it, is held to the budget of the first load: 60 KB gzip, with the scripts' 30 KB gzip and 100 KB raw
    files, first = first_load_files()
    files["assets/notfound-DDDDDDDD.js"] = os.urandom(31 * 1024)
    with pytest.raises(build.BudgetError, match=r"first-load JS of 404\.html is 31\.\d KB gzip \(limit 30 KB\)"):
        check(files, first)
    files, first = first_load_files()
    files["assets/notfound-DDDDDDDD.js"] = b"let n=1;\n" * (101 * 1024 // 9)
    with pytest.raises(build.BudgetError, match=r"first-load JS of 404\.html is 10\d\.\d KB raw \(limit 100 KB\)"):
        check(files, first)


def test_a_check_that_names_no_entry_page_measures_none_and_is_as_it_was():
    files, first = first_load_files()
    sizes = build.check_budgets(files, trio_pages=["trio/pal-mnk-ber/index.html"], first_load_assets={"trio/pal-mnk-ber/index.html": first["trio/pal-mnk-ber/index.html"]})
    assert not [key for key in sizes if key.startswith(("home_", "notfound_"))]


def test_the_build_measures_the_404_page_and_reports_both_pages_on_the_command_line(site, tmp_path, capsys):  # noqa: F811
    out, summary = site
    raw = (out / NOT_FOUND).read_bytes()
    assert summary.sizes["notfound_html"] == len(raw)
    assert summary.sizes["notfound_first_load_gzip"] <= build.LIMITS["first_load_gzip"]
    need_node()
    assert build.main(["--results", str(RESULTS), "--out", str(tmp_path / "dist"), "--noindex", "--sources-manifest", str(MANIFEST)]) == 0
    lines = capsys.readouterr().out.splitlines()
    home = next(line for line in lines if line.startswith("home page:"))
    nope = next(line for line in lines if line.startswith("404 page:"))
    for line in (home, nope):
        assert re.fullmatch(r"(?:home|404) page: \d+\.\d KB raw \(limit \d+ KB\), \d+\.\d KB gzip \(limit \d+ KB\); first load \d+\.\d KB gzip \(limit 60 KB\)", line), line


def test_the_build_refuses_a_404_page_over_its_limit_and_writes_nothing(tmp_path, monkeypatch):
    need_node()
    monkeypatch.setitem(build.LIMITS, "notfound_html", 1024)
    with pytest.raises(build.BudgetError, match=r"404 page 404\.html is \d+\.\d KB \(limit 1 KB\)"):
        run_build(tmp_path / "dist", tmp_path)
    assert not (tmp_path / "dist").exists()


def test_the_assets_of_a_build_name_the_script_of_the_404_page_beside_the_others():
    assert {"css", "boot", "app", "engine", "notfound"} == set(build.Assets.__dataclass_fields__)


# ---- what DECISIONS says about the 404 page and the canonical address -----------------------------------------------------------------------------


def decisions_line() -> str:
    lines = (REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines()
    return " ".join(next(line for line in lines if line.startswith("- 2026-10-18 The home picker")).split())


def test_decisions_records_the_accepted_limitation_the_steps_of_the_script_and_the_limits_the_build_enforces():
    text = decisions_line()
    limits = build.LIMITS
    # the limitation that was accepted, and why: a redirect for each order of each trio is more than the host takes
    for words in ("previews as", "Not found", "2,800", "2,000 static redirects"):
        assert words in text, f"the decision about the 404 page does not say: {words}"
    # the steps, in their order
    steps = [text.index(word) for word in ("cut at its slashes", "decoded once", "normalised", "looked up in the list", "location.replace")]
    assert steps == sorted(steps), "the steps of the script are not told in the order they are taken"
    for words in ("data-trios", "check_notfound_script", "first.js", "untouched", "analytics beacon", "page_script", "isSafeTarget", "#search"):
        assert words in text, f"the decision about the 404 page does not say: {words}"
    # the budgets of the two pages, as the build holds them
    assert f"the home page {limits['home_html'] // 1024} KB raw and {limits['home_html_gzip'] // 1024} KB gzip" in text
    assert f"the 404 page {limits['notfound_html'] // 1024} KB raw and {limits['notfound_html_gzip'] // 1024} KB gzip" in text
    assert "Before and after" in text
    # what the picker does and does not show
    for words in ("shows no race", "readQuery", "coming soon", "folded"):
        assert words in text, f"the decision about the picker does not say: {words}"


def test_the_decision_line_names_no_private_document_and_writes_no_count_the_private_flags_decide():
    text = decisions_line()
    assert not re.search(r"\b[Tt]ask \d|\bAppendix [A-Z]\b|\bPhase \d|amendment", text)
    counts = [int(n.replace(",", "")) for n in re.findall(r"([0-9][0-9,]*) (?:pages|items|records|names)(?![a-z])", text)]
    assert all(n < 100 for n in counts), "the line writes a count of pages or items of the real results"


def test_decisions_records_the_pasted_link_the_name_of_two_words_the_status_line_and_the_length_of_the_box():
    text = decisions_line()
    for words in ("trioAddress", "address bar", "shared kit", "shadow k", "the first three are used", "replaced only when", "MAX_QUERY_LENGTH", "maxlength", "2,500", "limit of 200 characters"):
        assert words in text, f"the decision about the picker does not say: {words}"


def test_decisions_records_the_policy_of_the_404_page_the_three_files_of_its_script_and_its_theme_button():
    text = decisions_line()
    for words in ("NOTFOUND_POLICY", "script-src 'self'; connect-src 'none'", "adds to the header's", "Web Analytics", "all three of its files", "theme button"):
        assert words in text, f"the decision about the 404 page does not say: {words}"
