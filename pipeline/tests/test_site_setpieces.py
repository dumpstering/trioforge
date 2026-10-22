"""The set pieces of the pages: a scene in a bevelled frame on the home, about, changelog and 404 pages, a character beside the text of the sources page, and the plain page when the art is missing.

The scenes are opaque pictures shown in a frame like a window of the late 90s, with a caption in text where the page has one; the characters are transparent and float beside their text. Each is a
decorative ``span`` that nothing reads (``aria-hidden``, no text, no style attribute), made by the existing mechanism of the art; a picture that is not part of the site leaves the page whole.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from site_helpers import parse
from test_site_build import NOT_FOUND, PAGES, page, site  # noqa: F401  (site: the build of the fixture, once for this module as well)
from test_site_home import stub_page, trios_made_of

from trioforge.site import art, build

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "pipeline" / "trioforge" / "site" / "static"

#: what each page shows besides the trio page's race picture: the scenes, in the order of the page, and the characters
SCENES = {"home": ["hero-trio", "plains", "dragon"], "about": ["city-gate"], "changelog": ["campfire"], "notfound": ["treetop-village", "hyenamen"], "sources": [], "rules": []}
CAPTIONS = {"treetop-village": "You fell off the platform."}


def shown(html, cls_prefix):
    return [n for n in html.find_all("span") if "art" in n.classes and any(c.startswith(cls_prefix) for c in n.classes)]


def test_each_page_has_its_scenes_in_a_frame_as_decoration_in_the_order_picked(site):  # noqa: F811
    out, _ = site
    for name, keys in SCENES.items():
        html = page(out, NOT_FOUND if name == "notfound" else PAGES[name])
        figures = html.find_all("figure", cls="shot")
        assert [[c for c in f.classes if c.startswith("shot-")] for f in figures] == [[f"shot-{k}"] for k in keys], name
        for figure, key in zip(figures, keys):
            spans = figure.find_all("span")
            assert [sorted(s.classes) for s in spans] == [["art", f"art-{key}"]], key
            assert spans[0].get("aria-hidden") == "true" and spans[0].text(skip_hidden=False) == "" and not spans[0].has("style"), key
            caption = figure.find_all("figcaption")
            assert len(caption) <= 1 and (not caption or caption[0].text().strip() != ""), key
            if key in CAPTIONS:
                assert caption[0].text() == CAPTIONS[key]


def test_the_sources_page_has_the_scholar_beside_its_first_words_and_the_trio_page_the_race_picture(site):  # noqa: F811
    out, _ = site
    sources = page(out, PAGES["sources"])
    assert [sorted(s.classes) for s in shown(sources, "art-scholar")] == [["art", "art-scholar"]]
    assert shown(sources, "art-scholar")[0].get("aria-hidden") == "true"
    assert not sources.find_all("figure", cls="shot")  # a character is not a screenshot: no frame
    trio = page(out, PAGES["trio"]).find("main")  # (the footer has two small characters of its own)
    race = shown(trio, "art-race-")
    assert [sorted(s.classes) for s in race] == [["art", "art-race-ogre"]]  # the fixture's best race is the Ogre
    assert race[0].get("aria-hidden") == "true" and not race[0].has("style")
    assert race[0].parent is not None and "best-race" in race[0].parent.classes
    for name in ("rules", "about", "changelog", "home"):
        assert not shown(page(out, PAGES[name]).find("main"), "art-race-"), name  # no race picture off the trio page
        assert not shown(page(out, PAGES[name]).find("main"), "art-scholar"), name


def words(html: str) -> str:
    """The text of the main part of a page, whitespace collapsed."""
    return parse(html).find("main").text(skip_hidden=False)


def test_the_pages_without_their_art_are_whole_and_say_the_same_but_for_the_captions(monkeypatch):
    live = trios_made_of(["pal-mnk-ber"])
    contexts = {"home.html.j2": build.home_context(live), "notfound.html.j2": build.notfound_context(live)}
    with_art = {name: stub_page(name, **extra) for name, extra in contexts.items()}
    assert "shot-hero-trio" in with_art["home.html.j2"] and "shot-dragon" in with_art["home.html.j2"] and "shot-treetop-village" in with_art["notfound.html.j2"]
    monkeypatch.setattr(art, "_assets", lambda: frozenset({"emblem"}))
    for name, extra in contexts.items():
        bare = stub_page(name, **extra)
        assert "shot" not in bare and "figcaption" not in bare and 'class="art art-' not in bare.split("<main", 1)[1], name
        captions = [c for keys in SCENES.values() for c in keys if c in CAPTIONS]
        text = words(with_art[name])
        for caption in ("Pick three. Wear the best.", "The best loot, still guarded.", "You fell off the platform.", "The lands where every trio begins.", "The locals have not seen this page either."):
            text = text.replace(caption, "")
        assert " ".join(words(bare).split()) == " ".join(text.split()), name
        assert parse(bare).find("h1").text() == parse(with_art[name]).find("h1").text()
    bare = stub_page("notfound.html.j2", **contexts["notfound.html.j2"])
    assert parse(bare).find("h1").text() == "Page not found" and "There is nothing at this address." in words(bare) and "Go to the home page" in words(bare)


def test_the_set_pieces_are_drawn_by_the_css_of_the_frame_with_whole_scales_and_a_phone_that_keeps_its_first_screen():
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "site.css").read_text(encoding="utf-8"), flags=re.DOTALL)

    def rule(selector: str) -> str:
        found = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^{}]*)\}", css)
        assert found, selector
        return " ".join(found.group(1).split())

    # the frame: a bevelled window with the picture in it (no inline style, no extra request: the picture is the background of the span)
    assert "border: 2px solid" in rule(".shot") and "box-shadow" in rule(".shot") and "display: block" in rule(".shot .art")
    # 3x from 1920 px (120rem), 2x below it, 4x from a 4K window (150rem, where the stylesheet doubles every scale)
    assert "--art-s: 3" in rule_in_media(css, "min-width: 120rem", ".shot .art") and "--art-s: 2" in rule_in_media(css, "min-width: 150rem", ".shot .art")
    assert css.index("@media (min-width: 120rem)") < css.index("@media (min-width: 150rem) {\n  .shot")
    # a phone: 1x, and the scenes that would be in its first screen are not shown (display: none on the span that carries the picture and on its frame)
    phone = " ".join(rule_in_media(css, "max-width: 37.5rem", ".shot-hero-trio .art-hero-trio").split())
    assert "display: none" in phone
    for key in ("hero-trio", "city-gate", "campfire"):
        assert "display: none" in rule_in_media(css, "max-width: 37.5rem", f".shot-{key} .art-{key}"), key
        assert "display: none" in rule_in_media(css, "max-width: 37.5rem", f".shot-{key}"), key
    assert "--art-s: 1" in rule_in_media(css, "max-width: 37.5rem", ".shot .art")
    assert "display: none" in rule_in_media(css, "max-width: 37.5rem", ".best-race .art")  # the race picture would push the first kit row below the first screen of a phone
    for key in ("dragon", "treetop-village"):
        assert f".shot-{key}" not in rule_in_media(css, "max-width: 37.5rem", ".shot-hero-trio .art-hero-trio") and f"shot-{key}" not in phone, key


def rule_in_media(css: str, query: str, selector: str) -> str:
    """The body of the rule that has ``selector`` among its selectors, inside a media block ``(query)`` (the first block that has one; the stylesheet has several blocks for a query)."""
    for opening in re.finditer(re.escape(f"@media ({query})") + r"\s*\{", css):
        depth, end = 1, opening.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        for found in re.finditer(r"([^{}]+)\{([^{}]*)\}", css[opening.end() : end - 1]):
            if selector in [part.strip() for part in found.group(1).split(",")]:
                return " ".join(found.group(2).split())
    raise AssertionError(f"{selector} has no rule in @media ({query})")


# ---- the menu ----------------------------------------------------------------------------------------------------------------------------------------


def test_the_menu_has_trios_about_and_changelog_and_the_pages_left_out_of_it_are_still_there_and_linked(site):  # noqa: F811
    """Rules and Sources are not in the menu (the user's choice), but both pages are built and reachable: the footer's "Sources and licences" link carries the CC BY-SA attribution, and the trio pages link into /rules/."""
    out, _ = site
    for name in [*PAGES.values(), NOT_FOUND]:
        html = page(out, name)
        header = html.find("header")
        assert [(a.get("href"), a.text()) for a in header.find("nav").find_all("a")] == [("/", "Trios"), ("/about/", "About"), ("/changelog/", "Changelog")], name
    assert page(out, PAGES["rules"]).find("h1").text() and page(out, PAGES["sources"]).find("h1").text()
    for name in [*PAGES.values(), NOT_FOUND]:
        footer = page(out, name).find("footer")
        assert [a.get("href") for a in footer.find_all("a") if a.text() == "Sources and licences"] or "/sources/" in [a.get("href") for a in footer.find_all("a")], name
    trio_links = [a.get("href") for a in page(out, PAGES["trio"]).find("main").find_all("a")]
    assert any(h.startswith("/rules/") for h in trio_links)
    assert "/sources/" in read_sitemap(out) and "/rules/" in read_sitemap(out)


def read_sitemap(out) -> str:
    return (out / "sitemap.xml").read_text(encoding="utf-8")


# ---- the second round of art: the plains, the hyena people, the icon of an item, the footer and the credit --------------------------------------------------------------


def test_the_item_pages_carry_the_icon_of_their_slot_beside_the_name_and_none_when_the_slot_has_none(site):  # noqa: F811
    from trioforge.site import view

    out, _ = site
    names = {name: group for group, name in view.SLOT_NAMES.items()}
    pages = sorted((out / "item").glob("*/index.html"))
    assert pages
    seen_icon = seen_none = False
    for path in pages:
        html = parse(path.read_text(encoding="utf-8"))
        slot = next(n for n in html.find_all("dt") if n.text() in ("Slot", "Slots")).parent.find("dd").text()
        want = art.item_icon([names[s] for s in slot.split(", ")])
        heading = html.find("h1")
        spans = heading.find_all("span")
        assert [sorted(s.classes) for s in spans] == ([["art", f"art-{want}"]] if want else []), (path.parent.name, slot)
        if want:
            assert spans[0].get("aria-hidden") == "true" and spans[0].text(skip_hidden=False) == "" and not spans[0].has("style")
            assert heading.text() == heading.text().strip() and heading.text() != ""
            seen_icon = True
        else:
            seen_none = True
    assert seen_icon and seen_none, "the fixture's items should show both a slot with an icon and one without"


def test_the_home_page_has_the_plains_above_the_list_and_the_404_page_the_hyena_people_beside_the_village(site):  # noqa: F811
    out, _ = site
    home = page(out, PAGES["home"])
    keys = [[c[5:] for c in f.classes if c.startswith("shot-")][0] for f in home.find_all("figure", cls="shot")]
    assert keys == ["hero-trio", "plains", "dragon"]
    main = home.find("main")
    order = [n for n in main.iter() if n.tag in ("figure", "section")]
    plains = next(n for n in order if n.tag == "figure" and "shot-plains" in n.classes)
    ready = next(n for n in order if n.tag == "section" and n.get("aria-labelledby") == "live-h")
    assert order.index(plains) < order.index(ready)
    lost = page(out, NOT_FOUND)
    assert [[c[5:] for c in f.classes if c.startswith("shot-")][0] for f in lost.find_all("figure", cls="shot")] == ["treetop-village", "hyenamen"]
    rows = lost.find_all("div", cls="scene-row")
    assert len(rows) == 1 and len(rows[0].find_all("figure")) == 2


def test_the_footer_has_two_small_characters_beside_its_badges_as_decoration_and_the_sources_page_credits_the_art(site):  # noqa: F811
    out, _ = site
    for name in [*PAGES.values(), NOT_FOUND]:
        footer = page(out, name).find("footer")
        sprites = [n for n in footer.find_all("span") if "art" in n.classes and any(c.startswith("art-race-") for c in c_all(n))]
        assert [sorted(c for c in s.classes if c != "art") for s in sprites] == [["art-foot", "art-race-froglok"], ["art-foot", "art-race-dwarf"]], name
        assert all(s.get("aria-hidden") == "true" and s.text(skip_hidden=False) == "" and not s.has("style") for s in sprites), name
        assert footer.find("ul", cls="badges") is not None
    sources = page(out, PAGES["sources"]).find("main").text()
    assert sources.count("The pixel art was made for TrioForge with Retro Diffusion.") == 1
    credit = [p for p in page(out, PAGES["sources"]).find("main").find_all("p") if "Retro Diffusion" in p.text()]
    assert len(credit) == 1 and not credit[0].find_all("a") and not credit[0].find_all("img")  # plain text: no logo and no link
    assert "Retro Diffusion" not in page(out, PAGES["about"]).find("main").text()  # (the About page has no credits paragraph)


def c_all(node) -> set[str]:
    return node.classes


def test_the_moving_things_of_every_page_are_at_most_three(site):  # noqa: F811
    from trioforge.site import art as art_module  # noqa: F401

    out, _ = site
    manifest = __import__("json").loads((STATIC / "art" / "manifest.json").read_text(encoding="utf-8"))["assets"]
    moving = {key for key, entry in manifest.items() if entry["kind"] == "strip" and len(entry["frames"]) > 1}
    for name in [*PAGES.values(), NOT_FOUND, "item/w1/index.html"]:
        path = out / name
        if not path.is_file():
            continue
        html = parse(path.read_text(encoding="utf-8"))
        counted = [n for n in html.find("body").iter() if n.tag == "span" and "art" in n.classes and any(c[4:] in moving - {"mail"} for c in n.classes if c.startswith("art-"))]  # (the mail moves only while its link is hovered or has the focus)
        assert len(counted) <= 3, (name, len(counted))
