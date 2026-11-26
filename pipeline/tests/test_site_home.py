"""The home page: the picker with its search, the list of every trio page that works without JavaScript, and the one canonical address of a trio.

A trio's page is ``/trio/<x>-<y>-<z>/`` with the classes in the site's own order (``classes.CLASS_CODES``), and its canonical link, the home page's list, the picker's list, the
sitemap and the list the 404 page canonicalizes against all name it the same way. Builds of five trios are made from copies of the fixture (as ``test_site_files.py`` makes three);
the home page of the full grid of 560 trios is rendered from the template with made-up entries, since 560 builds of the fixture would take longer than the test is worth.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

import pytest
from site_helpers import parse
from test_site_build import (
    NOT_FOUND,
    PAGES,
    RESULTS,
    SITE_URL,
    need_node,
    page,
    read,
    reindex,
    run_build,
    site,  # noqa: F401  (a fixture of test_site_build: the build of the fixture, once for this module as well)
)

from trioforge.classes import CLASS_CODES, CLASS_NAMES
from trioforge.site import build, content, data, view

REPO = Path(__file__).resolve().parents[2]
#: five trios in the order of their codes, which is the order the home page and the 404 page list them in. None has a class that Wood Elf (the fixture's third race) can start, so the
#: default race of the fixture still holds for each; each has a class that Ogre and Troll can start, which makes them legal races for it.
FIVE = ("clr-pal-shd", "clr-shd-ber", "clr-shd-mnk", "pal-mnk-ber", "pal-shd-ber")  # (copies of the fixture's Tank: each of these opens on the Tank, as its defaults.json says)


def many_trios(root: Path, slugs: tuple[str, ...] = FIVE) -> Path:
    """The results of several trios: the fixture's, and copies of it named for the other trios (the files name their trio, so each copy is changed to say so)."""
    scratch = root / "results"
    shutil.copytree(RESULTS, scratch)
    for slug in slugs:
        if slug == "pal-mnk-ber":
            continue
        folder = scratch / slug
        shutil.copytree(scratch / "pal-mnk-ber", folder)
        codes = [code.upper() for code in slug.split("-")]
        for path in folder.rglob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            if path.name == "engine-l50.json":  # the bundle names its trio as three class codes, twice
                document["trio"] = document["profile_common"]["trio"] = codes
            else:
                document["trio"] = slug
                if "classes" in document:
                    document["classes"] = codes
            path.write_text(json.dumps(document), encoding="utf-8")
        reindex(folder / "runnerups")  # the runner-up files changed, so their index follows
    return scratch


@pytest.fixture(scope="module")
def five(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("five")
    out = tmp / "dist"
    summary = run_build(out, tmp, results=many_trios(tmp))
    return SimpleNamespace(out=out, summary=summary)


def name_of(slug: str) -> str:
    return " / ".join(CLASS_NAMES[code.upper()] for code in slug.split("-"))


def every_trio() -> list[str]:
    """All 560 trios of the sixteen classes, as the codes of their pages, sorted the way the build lists the folders of the results."""
    return sorted("-".join(code.lower() for code in codes) for codes in combinations(CLASS_CODES, 3))


def stub_page(template: str, **extra) -> str:
    """A page of the frame rendered with made-up trios, through the context the build gives the template (``build.home_context`` and ``build.notfound_context``)."""
    book = content.load_rulebook(REPO / "rules" / "rules.json")
    context = dict(
        page_title="Title",
        page_description="Description",
        canonical=f"{SITE_URL}/",
        noindex=False,
        favicon=build.FAVICON,
        assets=SimpleNamespace(css="/assets/site-AAAAAAAA.css", boot="/assets/boot-BBBBBBBB.js", app="/assets/app-CCCCCCCC.js", notfound="/assets/notfound-DDDDDDDD.js"),
        nav=build._nav("/"),
        meta=SimpleNamespace(data_date="2026-10-14", game_patch="2026-09-22", level=50, data_tag="data-2026-10-14"),
        disclaimer=build.DISCLAIMER,
        attribution=build.ATTRIBUTION,
        attribution_parts=build.attribution_parts(),
        licence_sentence=build.LICENCE_SENTENCE,
        level_rule=view.rule_ref(book, "level.current"),
        partial=False,
        reports_not_open=build.REPORTS_NOT_OPEN,
        report_url=None,
    )
    context.update(extra)
    return build.make_env().get_template(template).render(**context)


def trios_made_of(slugs: list[str]) -> list[SimpleNamespace]:
    """The entries the build keeps of the trios it made: the code of the page, its name and the level."""
    return [SimpleNamespace(slug=slug, name=name_of(slug), level=50) for slug in slugs]


def home_html(slugs: list[str]) -> str:
    return stub_page("home.html.j2", **build.home_context(trios_made_of(slugs)))


def gz(text: str) -> int:
    return len(gzip.compress(text.encode("utf-8"), 9, mtime=0))


# ---- the picker and its search ------------------------------------------------------------------------------------------------------------


def test_the_picker_is_hidden_until_the_script_runs_and_holds_the_search_the_chips_and_the_answer(site):  # noqa: F811
    out, _ = site
    html = page(out, PAGES["home"])
    picker = html.by_id("picker")
    assert picker.has("hidden") and picker.get("data-live") == "pal-mnk-ber"
    assert picker.tag == "section" and picker.get("aria-labelledby") == "pick-h"
    assert html.by_id("pick-h").parent is picker  # the heading is hidden with the rest: a visitor without the script is not shown a heading with nothing under it
    search = picker.by_id("trio-search")
    assert search.tag == "input" and search.get("type") == "search"
    label = picker.find("label", **{"for": "trio-search"})
    assert label.text() == "Search for a trio"
    hint = picker.by_id("trio-search-hint")
    assert search.get("aria-describedby") == "trio-search-hint"
    assert "pal mnk ber" in hint.text() and "paladin monk berserker" in hint.text() and "any order" in hint.text()
    boxes = picker.find_all("input", type="checkbox")
    assert [b.get("value") for b in boxes] == list(CLASS_CODES)  # EQ class-id order
    assert picker.by_id("picker-status").get("role") == "status" and picker.by_id("picker-status").get("aria-live") == "polite"
    assert picker.by_id("picker-status").text() == "" and picker.by_id("picker-status").children == []  # nothing is said until a class is chosen: the heading says to pick three


def test_the_search_box_asks_a_keyboard_not_to_correct_or_complete_what_is_typed(site):  # noqa: F811
    out, _ = site
    search = page(out, PAGES["home"]).by_id("trio-search")
    assert search.get("autocomplete") == "off" and search.get("autocorrect") == "off" and search.get("autocapitalize") == "off" and search.get("spellcheck") == "false"  # codes are not words


def test_the_search_box_takes_as_many_characters_as_the_picker_reads_which_is_more_than_the_longest_link_to_a_shared_kit(site):  # noqa: F811
    out, _ = site
    search = page(out, PAGES["home"]).by_id("trio-search")
    source = (REPO / "pipeline" / "trioforge" / "site" / "static" / "picker.js").read_text(encoding="utf-8")
    limit = int(re.search(r"export const MAX_QUERY_LENGTH = (\d+);", source).group(1))
    assert search.get("maxlength") == str(limit)  # the box and the script hold one number
    # a link as the Share button makes one, and the longest the page takes (the codec reads 2,048 characters of kit): with a long address and the longest query of a view, it fits
    longest = "https://trioforge.pages.dev/trio/pal-mnk-ber/?race=OGR&role=tank&tier=10&setup=1h-shield&ev=strict&buffs=group#k=" + "A" * 2048
    assert len(longest) <= limit <= 4096


def test_the_home_page_has_no_form_and_no_id_twice(site):  # noqa: F811
    out, _ = site
    html = page(out, PAGES["home"])
    assert html.find_all("form") == []  # the policy forbids a form from sending anywhere (form-action 'none'): the search is the script's
    ids = [n.get("id") for n in html.iter() if n.has("id")]
    assert len(ids) == len(set(ids)), "an id twice"


# ---- the list of every trio page, without JavaScript ---------------------------------------------------------------------------------------------


def test_the_home_page_lists_every_built_trio_as_a_link_that_works_without_the_script(five):
    html = page(five.out, PAGES["home"])
    links = html.by_id("live-trios").find_all("a")
    assert [a.get("href") for a in links] == [f"/trio/{slug}/" for slug in FIVE]
    assert [a.text() for a in links] == [f"{name_of(slug)}: best gear (level 50)" for slug in FIVE]
    assert html.by_id("picker").get("data-live") == " ".join(FIVE)
    for slug in FIVE:
        assert (five.out / "trio" / slug / "index.html").is_file()
    assert html.by_id("picker").has("hidden"), "the picker needs the script, the list does not"
    assert html.find_all("details") == [], "a few trios are listed in the page itself"
    main = html.find("main").text()
    assert "coming soon" in main.lower()


def test_the_list_is_folded_into_an_expander_when_there_are_many_trios_and_every_link_is_still_in_the_page():
    assert "<details" not in home_html(list(FIVE))
    many = every_trio()
    assert len(many) == 560
    html = parse(home_html(many))
    box = html.by_id("all-trios")
    assert box.tag == "details" and box.get("class") == "expander" and not box.has("open")
    assert box.find("summary").text() == "List all 560 trios"
    links = box.by_id("live-trios").find_all("a")
    assert [a.get("href") for a in links] == [f"/trio/{slug}/" for slug in many]
    assert html.by_id("picker").get("data-live").split(" ") == many
    # a list a little over the number that stays open is folded, and one at the number is not
    assert parse(home_html(many[: build.HOME_LIST_OPEN + 1])).by_id("all-trios").tag == "details"
    assert parse(home_html(many[: build.HOME_LIST_OPEN])).find_all("details") == []


def test_the_page_says_coming_soon_while_a_trio_is_missing_and_says_all_are_ready_when_none_is(site):  # noqa: F811
    out, _ = site
    assert "Every other trio is coming soon." in page(out, PAGES["home"]).find("main").text()
    full = parse(home_html(every_trio())).find("main").text()
    assert "coming soon" not in full.lower() and parse(home_html(every_trio())).by_id("live-h").text() == "Trios"
    almost = parse(home_html(every_trio()[:-1])).find("main").text()
    assert "Every other trio is coming soon." in almost and parse(home_html(every_trio()[:-1])).by_id("live-h").text() == "Trios"


def test_the_home_page_of_the_full_grid_is_within_the_budget_of_its_page():
    text = home_html(every_trio())
    raw = len(text.encode("utf-8"))
    assert raw <= build.LIMITS["home_html"] and gz(text) <= build.LIMITS["home_html_gzip"], (raw, gz(text))
    assert build.LIMITS["home_html"] == 80 * 1024 and build.LIMITS["home_html_gzip"] == 12 * 1024
    # the list is most of it: a trio is about 90 bytes of markup, and the page without the trios is a few KB
    assert raw > 40 * 1024


def test_the_home_page_loads_the_stylesheet_the_boot_script_and_the_page_script_and_nothing_else(site):  # noqa: F811
    out, summary = site
    html = page(out, PAGES["home"])
    assert [(s.get("src").split("-")[0], s.get("type")) for s in html.find_all("script")] == [("/assets/boot", None), ("/assets/app", "module")]
    assert len(html.find_all("link", rel="stylesheet")) == 1
    sizes = summary.sizes
    raw = (out / "index.html").read_bytes()
    assert sizes["home_html"] == len(raw) and sizes["home_html_gzip"] == len(gzip.compress(raw, 9, mtime=0))
    first = [*(out / "assets").glob("site-*.css"), *(out / "assets").glob("boot-*.js"), *(out / "assets").glob("app-*.js")]  # (the stylesheet and the two scripts)
    assert len(first) == 3
    assert sizes["home_first_load_gzip"] == sizes["home_html_gzip"] + sum(len(gzip.compress(p.read_bytes(), 9, mtime=0)) for p in first)
    assert sizes["home_first_load_gzip"] <= build.LIMITS["first_load_gzip"]


# ---- the canonical address of a trio ----------------------------------------------------------------------------------------------------------------


def test_every_trio_page_says_its_own_address_in_the_order_of_the_sites_classes_and_every_list_agrees(five):
    out = five.out
    expected = [f"{SITE_URL}/trio/{slug}/" for slug in FIVE]
    canonical = []
    for slug in FIVE:
        link = page(out, f"trio/{slug}/index.html").find("link", rel="canonical")
        canonical.append(link.get("href"))
        order = [CLASS_CODES.index(code.upper()) for code in slug.split("-")]
        assert order == sorted(set(order)), f"{slug} is not in the order of the classes"
    assert canonical == expected
    sitemap = read(out, "sitemap.xml")
    assert re.findall(r"<loc>([^<]*/trio/[^<]*)</loc>", sitemap) == expected
    home = page(out, PAGES["home"])
    assert [a.get("href") for a in home.by_id("live-trios").find_all("a")] == [url.removeprefix(SITE_URL) for url in expected]
    notfound = page(out, NOT_FOUND).find("main")
    assert notfound.get("data-trios").split(" ") == list(FIVE)
    manifest = json.loads(read(out, "engine-manifest.json"))
    assert sorted(manifest["trios"]) == list(FIVE)  # the optimizer's own list of the trios says the same


def test_a_trio_page_names_no_other_address_as_its_canonical_one(five):
    for slug in FIVE:
        html = page(five.out, f"trio/{slug}/index.html")
        links = html.find_all("link", rel="canonical")
        assert len(links) == 1
        assert links[0].get("href") == f"{SITE_URL}/trio/{slug}/"
        assert html.find_all("meta", name="robots") == []  # (an indexable build)


def test_a_folder_of_results_named_for_a_trio_in_another_order_is_refused(tmp_path):
    need_node()
    scratch = many_trios(tmp_path, ("pal-mnk-ber",))
    shutil.copytree(scratch / "pal-mnk-ber", scratch / "ber-mnk-pal")
    with pytest.raises(data.ResultsError, match="class-id order"):
        run_build(tmp_path / "dist", tmp_path, results=scratch, noindex=True)
    assert not (tmp_path / "dist").exists()  # nothing was written
