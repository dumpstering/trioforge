"""The layout polish of the home page, the trio page and the footer (branch layout-polish): the markup the browser tests measure.

Nothing here is about a number: the key to the seals (said once on a trio page, and a title on every marker), the settings block (Race, Role and Tier, and the assumptions as one folded line), the
home page (one picture, a picker whose status line is empty until a class is chosen, a first sentence that says what a trio is) and the footer (a row of links, four badges). The boxes themselves
are measured in a browser (``tests-e2e/layout.spec.mjs``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from site_helpers import parse
from test_site_build import NOT_FOUND, PAGES, need_node, page, run_build, site  # noqa: F401  (site: the build of the fixture, indexable and with an owner, once for this module as well)
from test_site_home import FIVE, five  # noqa: F401  (five: a fixture of test_site_home, the build of five trios)

from trioforge.site import build, content

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "pipeline" / "trioforge" / "site" / "static"


@pytest.fixture(scope="module")
def site_closed(tmp_path_factory):
    """A preview built with no owner: it has no report link, and says when reports open."""
    need_node()
    tmp = tmp_path_factory.mktemp("site-closed")
    out = tmp / "dist"
    run_build(out, tmp, noindex=True, owner=None)
    return out


def seal_kind(node) -> str:
    return next(c[len("seal-") :] for c in node.classes if c.startswith("seal-"))


def first_child(node):
    """The first child that is an element (the text between tags is left out)."""
    return next(c for c in node.children if not isinstance(c, str))


# ---- the key to the seals --------------------------------------------------------------------------------------------------------------------


def test_every_trio_page_says_once_what_the_developer_and_the_model_markers_mean_in_the_words_of_the_rules_page(five):  # noqa: F811
    developer, model = content.SEALS["developer"], content.SEALS["model"]
    for slug in FIVE:
        html = page(five.out, f"trio/{slug}/index.html")
        keys = [n for n in html.iter() if n.get("id") == "seal-key"]
        assert len(keys) == 1, slug
        key = keys[0]
        assert key.tag == "p" and developer[1] in key.text() and model[1] in key.text(), slug
        assert [seal_kind(n) for n in key.find_all("span", cls="seal")] == ["developer", "model"] and not any(n.has("title") for n in key.find_all("span", cls="seal")), slug  # the key shows the two markers it names
        answer = html.find("section", cls="answer")
        assert key.parent is answer, "the key is in the answer's section, under its heading and above the kit table, so that it is read before the first row"
        order = [n.get("id") for n in answer.iter() if n.get("id") in ("wear-h", "seal-key", "kit", "kit-rules")]
        assert order == ["wear-h", "seal-key", "kit", "kit-rules"], slug
        assert "All the seals" in key.text() and key.find("a").get("href") == "/rules/#seals-h"
    # a page of another kind has no such line (the element is looked for by its id: the text of a node never holds one)
    for name in ("index.html", "about/index.html", "rules/index.html", "sources/index.html", "changelog/index.html"):
        other = page(five.out, name)
        assert not any(n.get("id") == "seal-key" for n in other.iter()), name
        assert "All the seals" not in other.find("main").text(), name


def test_the_developer_and_the_model_markers_of_every_page_carry_a_title_that_says_what_they_mean_and_the_others_are_as_they_were(site, five):  # noqa: F811
    out, _ = site
    meaning = {key: words for key, (_, words) in content.SEALS.items()}
    assert content.SEALS_TO_EXPLAIN == ("developer", "model")
    names = [*PAGES.values(), NOT_FOUND, "item/w1/index.html"]
    seen = titled = 0
    for name in names:
        path = out / name
        if not path.is_file():
            continue
        for node in parse(path.read_text(encoding="utf-8")).find("body").find_all("span", cls="seal"):
            kind = seal_kind(node)
            if node.parent.get("id") == "seal-key":  # (the key says it in words beside its markers, and they have no title)
                continue
            assert node.get("title") == (meaning[kind] if kind in content.SEALS_TO_EXPLAIN else None), (name, kind, node.get("title"))
            seen += 1
            titled += node.has("title")
    assert seen > 40 and titled > 10, (seen, titled)  # the trio page alone has dozens
    # the marker of the sidebar's last line (the data strip, on every page) is one of them, and so is every one on a trio page (the key beside its words has none: it says them)
    for slug in FIVE:
        html = page(five.out, f"trio/{slug}/index.html")
        assert html.find("p", cls="data-strip").find("span", cls="seal").get("title") == meaning["developer"]
        assert all(n.has("title") for n in html.find_all("span", cls="seal") if seal_kind(n) in content.SEALS_TO_EXPLAIN and n.parent.get("id") != "seal-key")


# ---- the settings block ----------------------------------------------------------------------------------------------------------------------


def test_the_assumptions_are_one_folded_details_element_whose_summary_says_the_choices_and_which_opens_to_the_controls_as_they_were(site):  # noqa: F811
    out, _ = site
    html = page(out, PAGES["trio"])
    folded = html.by_id("assumes")
    assert folded.tag == "details" and not folded.has("open") and folded.parent is html.by_id("switches")
    summary = folded.find("summary")
    assert first_child(folded) is summary
    assert summary.find(data_f="a-lead").text() == "Assumptions"  # (it says it is changed when one is: the page code writes it)
    line = summary.find(data_f="s-assumes").text()
    assert line == html.by_id("view-summary").find(data_f="s-assumes").text() and "your own buffs" in line  # the words of the folded line of a phone
    assert summary.text() == f"Assumptions: {line}"
    # the controls inside are the ones there were: the three assumptions, each a details element with its own summary and fieldset, and the AA line
    assert [d.get("id") for d in folded.find_all("details")] == ["assume-buffs", "assume-weapons", "assume-weights"]
    assert [i.get("value") for i in folded.find_all("input", name="buffs")] == ["own", "group", "raid"]
    assert folded.by_id("assume-aa").parent is folded
    # and Race, Role and Tier are the three choices of one block, with the role's hint under them
    controls = html.find("section", cls="controls")
    assert [n.get("id") for n in controls.iter() if n.get("id") in ("sw-race", "sw-role", "sw-tier", "role-hint")] == ["sw-race", "sw-role", "sw-tier", "role-hint"]
    assert not any(n.get("id") == "assumes-h" for n in html.iter()), "no heading of its own: the summary is the name of the disclosure"


# ---- the home page ---------------------------------------------------------------------------------------------------------------------------


def test_the_home_page_has_one_picture_the_archway_in_the_first_words_and_none_of_the_other_two(site):  # noqa: F811
    out, _ = site
    html = page(out, PAGES["home"])
    figures = html.find_all("figure", cls="shot")
    assert [[c for c in f.classes if c.startswith("shot-")] for f in figures] == [["shot-hero-trio"]]
    main = html.find("main")
    intro = figures[0].parent
    assert intro.tag == "div" and intro.get("class") == "intro" and [c.get("class") for c in intro.children if not isinstance(c, str)] == ["lead", "shot shot-hero-trio"], "the words, then the picture: beside them on a wide window, under them on a phone"
    assert not main.find_all("span", cls="art-plains") and not main.find_all("span", cls="art-dragon")
    assert not main.find_all("figcaption"), "the picture has no caption: a caption would say Pick three a fourth time"
    assert figures[0].get("aria-hidden") == "true", "a frame with nothing to read in it is hidden from assistive technology, as its picture is"


def test_the_home_page_says_pick_three_classes_once_in_the_heading_and_the_group_label_and_the_status_line_are_quiet(site):  # noqa: F811
    out, _ = site
    html = page(out, PAGES["home"])
    picker = html.by_id("picker")
    assert picker.find("h2").text() == "Pick your three classes"
    legend = picker.find("legend")
    assert "sr-only" in legend.classes and legend.text() == "Classes (choose three)"  # for a screen reader, and not seen
    status = picker.by_id("picker-status")
    assert status.get("role") == "status" and status.get("aria-live") == "polite"
    assert status.text() == "" and status.children == [], "empty in the page: the script says something once a class is chosen"
    seen = " ".join(n.text() for n in (picker.find("h2"), *picker.find_all("p")) if "sr-only" not in n.classes)
    assert len(re.findall(r"pick (?:your )?three classes|choose three", seen, flags=re.I)) == 1, seen  # (the hint under the search box says what to type, not what to pick)


def test_the_first_words_of_the_home_page_say_what_a_trio_is_and_the_rest_of_the_intro_is_kept(site):  # noqa: F811
    out, _ = site
    lead = page(out, PAGES["home"]).find("p", cls="lead").text()
    assert lead.startswith("A trio is the three classes one character combines in EverQuest Legends. ")
    assert lead.endswith("Pick three classes and see the one kit to wear: exact answers, with the evidence and the confidence behind every rule. TrioForge is a fan project.")
    assert lead.count("EverQuest Legends") == 1, "the game is named once"


# ---- the footer ------------------------------------------------------------------------------------------------------------------------------


def foot_row(out, name):
    footer = page(out, name).find("footer")
    rows = footer.find_all("ul", cls="foot-links")
    assert len(rows) == 1, name
    return footer, rows[0]


def test_the_footer_has_one_row_of_three_links_with_no_separator_when_the_report_link_is_there(site):  # noqa: F811
    out, _ = site
    for name in [*PAGES.values(), NOT_FOUND]:
        footer, row = foot_row(out, name)
        items = row.find_all("li")
        assert [i.text() for i in items] == ["Report a problem with this page", "About", "Changelog"], name
        assert items[0].find("a").get("id") == "report-link" and [i.find("a").get("href") for i in items[1:]] == ["/about/", "/changelog/"], name
        assert not re.search(r"[·|•]", row.text()) and "&middot;" not in (out / name).read_text(encoding="utf-8").split('class="foot-links"', 1)[1].split("</ul>", 1)[0], name
        assert "Reports open when the project is public" not in footer.text(), name


def test_the_footer_row_is_clean_when_the_report_link_is_absent_and_has_the_note_in_its_place(site_closed):
    for name in [*PAGES.values(), NOT_FOUND]:
        footer, row = foot_row(site_closed, name)
        items = row.find_all("li")
        assert [i.text() for i in items] == [build.REPORTS_NOT_OPEN, "About", "Changelog"], name
        assert not items[0].find_all("a") and [i.find("a").get("href") for i in items[1:]] == ["/about/", "/changelog/"], name
        assert not re.search(r"[·|•]", row.text()), name
        assert all(i.text() and not re.fullmatch(r"[s·|•/-]+", i.text()) for i in items), name  # never an item that is only a separator


def test_the_footer_links_are_a_flex_row_whose_links_are_flex_lines_so_that_the_report_link_keeps_its_picture_beside_its_words():
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "site.css").read_text(encoding="utf-8"), flags=re.DOTALL)

    def body(selector: str) -> str:
        found = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^{}]*)\}", css)
        assert found, selector
        return " ".join(found.group(1).split())

    row = body(".foot-links")
    assert "display: flex" in row and "flex-wrap: wrap" in row and "align-items: center" in row and "justify-content: center" in row
    # a rule that is as heavy as .report-link's and comes after it must not turn the link into a block that puts the picture over the words: the links are flex lines, and level with each other
    link = body(".foot-links a")
    assert "display: inline-flex" in link and "align-items: center" in link


def test_the_four_badges_are_the_same_kind_of_thing_and_the_notepad_badge_is_a_link_to_the_changelog(site):  # noqa: F811
    out, _ = site
    for name in [*PAGES.values(), NOT_FOUND]:
        footer = page(out, name).find("footer")
        badges = footer.find("ul", cls="badges").find_all("li")
        assert len(badges) == 4, name
        nodes = [li.children[0] for li in badges]
        assert all("badge" in n.classes for n in nodes), name
        assert sorted(n.text() for n in nodes) == ["Best in Slot", "Data: eqlwiki CC BY-SA", "Latest changes", "TrioForge"], name
        assert [n.get("href") for n in nodes if n.tag == "a"] == ["/sources/", "/changelog/"], name
        assert "Notepad" not in footer.text(skip_hidden=False), name
    stylesheet = (STATIC / "site.css").read_text(encoding="utf-8")
    assert "Notepad" not in stylesheet


# ---- the budget of the page ------------------------------------------------------------------------------------------------------------------


def test_the_largest_page_of_a_trio_is_within_the_budget_and_the_budget_is_what_the_decisions_say():
    decisions = (REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    raised = [line for line in decisions.splitlines() if "layout-polish" in line and "trio_html" in line]
    limit = build.LIMITS["trio_html"]
    assert limit == 67584 or (67584 < limit <= 67584 + 2048 and raised), (limit, "a raise of the page's limit is one line of DECISIONS.md, old and new and why, and at most 2,048 bytes")
