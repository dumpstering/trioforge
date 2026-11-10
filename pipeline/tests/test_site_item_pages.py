"""Item pages in a built site: the files, the frame, the tables, the links to them and the budgets.

The fixture's items are invented (``fixtures/site/results``); a page that needs an item the fixture lacks is made from a copy of the fixture with the record changed.
The model of a page (the figures, the facts, the sources and the notes) is held to ``at_tier`` in ``test_site_items.py``; these tests read the pages the build writes.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import re
import shutil
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from site_helpers import parse
from test_site_build import MANIFEST, OWNER, RESULTS, SITE_URL, need_node, page, read, reindex, run_build
from test_site_items import expected_rows, number

from trioforge import rules as rules_module
from trioforge.classes import CLASS_CODES
from trioforge.export import browser
from trioforge.site import build, content, data, view

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "rules" / "rules.json"
TIERS = range(11)


def item_files(out: Path) -> list[str]:
    return sorted(p.relative_to(out).as_posix() for p in (out / "item").glob("*/index.html"))


def item_html(out: Path, key: str):
    return page(out, f"item/{key}/index.html")


@pytest.fixture(scope="module")
def table():
    return json.loads((RESULTS / "items.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def records(table):
    return {browser.record_key(record): record for record in table["items"]}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("item-pages")
    out = tmp / "dist"
    summary = run_build(out, tmp)
    return SimpleNamespace(out=out, summary=summary)


# ---- the files ----------------------------------------------------------------------------------------------------------------------------


def test_the_build_writes_one_page_for_each_strict_or_wiki_wearable_and_none_for_any_other_item(built, table):
    keys = build.item_page_keys(table)
    assert item_files(built.out) == [f"item/{key}/index.html" for key in keys]
    assert len(keys) == 47 and built.summary.sizes["item_pages"] == 47
    assert "item/w90041/index.html" not in built.summary.pages  # a hidden helm
    assert all(f"item/{key}/index.html" in built.summary.pages for key in keys)
    assert not (built.out / "item" / "w90041").exists() and not (built.out / "item" / "index.html").exists()  # (no page for the folder either)


def test_a_disputed_item_and_a_hidden_item_have_no_page_and_nothing_in_the_site_links_to_them(tmp_path, table):
    need_node()
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    changed = json.loads((results / "items.json").read_text(encoding="utf-8"))
    by_key = {browser.record_key(r): r for r in changed["items"]}
    by_key["w90040"]["evidence"] = {"level": "disputed", "codes": ["out-of-era-tag-live-zone"]}  # a cap no kit wears: strict -> disputed
    (results / "items.json").write_text(json.dumps(changed), encoding="utf-8")
    out = tmp_path / "dist"
    summary = run_build(out, tmp_path, results=results, noindex=True)
    files = item_files(out)
    assert len(files) == 46 and "item/w90040/index.html" not in files and "item/w90041/index.html" not in files
    assert summary.sizes["item_pages"] == 46
    for path in sorted(out.rglob("*.html")):  # no link to either, in any page
        text = path.read_text(encoding="utf-8")
        assert "/item/w90040/" not in text and "/item/w90041/" not in text, path.name
    assert "/item/w90001/" in read(out, "trio/pal-mnk-ber/index.html")


def test_an_item_with_a_page_and_no_wiki_page_in_the_manifest_stops_the_build(tmp_path):
    need_node()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    del manifest["items"]["w90040"]  # a strict cap that no kit wears: it has a page, so it needs its credit
    broken = tmp_path / "manifest.json"
    broken.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(build.BuildError, match=r"w90040.*(page|credit)"):
        run_build(tmp_path / "dist", tmp_path, sources_manifest=broken)


def test_an_item_with_no_wiki_page_has_a_page_with_no_credit_and_the_other_pages_keep_theirs(tmp_path):
    """An item that has no page on the wiki (no page id, a key of its own) has nothing to credit, so the manifest of the wiki pages need not have it and its page has no credit
    section; a page of an item from the wiki is as it was."""
    need_node()
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    changed = json.loads((results / "items.json").read_text(encoding="utf-8"))
    cap = next(r for r in changed["items"] if browser.record_key(r) == "w90040")  # the cap no kit wears: only its page shows it
    cap["id"], cap["key"] = None, "rmoon-cap"
    (results / "items.json").write_text(json.dumps(changed), encoding="utf-8")
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=results, noindex=True)
    html = item_html(out, "rmoon-cap")
    assert [h.text() for h in html.find("main").find_all("h2")] == ["Stats by tier", "Sources", "Best for these trios"]
    assert html.find_all(None, id_="credit") == [] and html.find_all(None, id_="credit-h") == []
    assert [a.get("href") for a in html.find("main").find_all("a") if "eqlwiki.com" in a.get("href", "")] == []  # (no link to a wiki page that is not there)
    assert "Wiki credit" not in read(out, "item/rmoon-cap/index.html")
    other = item_html(out, "w90001")
    assert [h.text() for h in other.find("main").find_all("h2")][-1] == "Wiki credit" and other.by_id("credit") is not None


# ---- the frame of a page -------------------------------------------------------------------------------------------------------------------


def test_an_item_page_has_the_frame_title_description_canonical_address_and_report_link_of_a_page(built):
    html = item_html(built.out, "w90001")
    assert html.find("html").get("lang") == "en"
    assert html.find("title").text() == "Helm of the Stoneward · TrioForge"
    assert "Helm of the Stoneward" in html.find("meta", name="description").get("content")
    assert html.find("link", rel="canonical").get("href") == f"{SITE_URL}/item/w90001/"
    assert html.find_all("meta", name="robots") == []  # (an indexable build)
    main = html.find("main")
    assert main.get("id") == "main" and main.get("tabindex") == "-1" and main.get("data-page") == "item"
    first = next(n for n in html.find("body").iter() if n.tag in ("a", "button", "input", "select", "summary"))
    assert first.tag == "a" and first.get("href") == "#main" and "skip-link" in first.classes
    assert [h.text() for h in html.find_all("h1")] == ["Helm of the Stoneward"]
    link = html.find("footer").by_id("report-link")
    query = parse_qs(urlparse(link.get("href")).query)
    assert query["template"] == ["wrong-item.yml"] and query["page"] == [f"{SITE_URL}/item/w90001/"] and "Helm of the Stoneward" in query["title"][0]


def test_an_item_page_has_the_footer_line_of_the_data_and_the_patch_and_the_disclaimer_and_attribution_of_every_page(built):
    html = item_html(built.out, "w90001")
    assert re.sub(r"\s+", " ", html.find(cls="data-strip").text()).startswith("Data: 2026-10-14 · Game patch: 2026-09-22")
    footer = html.find("footer").text()
    assert build.DISCLAIMER in footer and build.ATTRIBUTION in footer


def test_every_item_page_has_one_h1_in_order_headings_unique_ids_and_tables_with_captions_and_scoped_headers(built, table):
    for key in build.item_page_keys(table):
        html = item_html(built.out, key)
        assert len(html.find_all("h1")) == 1, key
        levels = [int(h.tag[1]) for h in html.iter() if re.fullmatch(r"h[1-6]", h.tag)]
        assert levels[0] == 1 and all(b - a <= 1 for a, b in zip(levels, levels[1:])), (key, levels)
        ids = [n.get("id") for n in html.iter() if n.has("id")]
        assert len(ids) == len(set(ids)), (key, [i for i in ids if ids.count(i) > 1])
        for one in html.find_all("table"):
            assert one.find("caption") is not None, key
            assert all(th.get("scope") in ("col", "row") for th in one.find_all("th")), key
        for svg in html.find_all("svg"):
            if svg.parent.tag != "body":
                assert svg.get("aria-hidden") == "true", key


def test_the_noindex_build_marks_its_item_pages_as_it_marks_the_others(tmp_path):
    need_node()
    out = tmp_path / "dist"
    run_build(out, tmp_path, noindex=True)
    assert item_html(out, "w90001").find("meta", name="robots").get("content") == "noindex"
    assert item_html(out, "w90001").find("link", rel="canonical") is not None
    assert not (out / "sitemap.xml").exists()


# ---- the tier table ------------------------------------------------------------------------------------------------------------------------


def table_of(html, ident: str):
    node = html.by_id(ident)
    head = [th.text() for th in node.find("thead").find_all("th")]
    body = {tr.find("th").text(): [td.text() for td in tr.find_all("td")] for tr in node.find("tbody").find_all("tr")}
    return node, head, body


def test_the_table_of_tiers_has_the_tiers_as_its_headers_and_a_row_for_each_stat(built):
    node, head, body = table_of(item_html(built.out, "w90001"), "tiers")
    assert head == ["Stat", *(f"+{tier}" for tier in TIERS)]
    assert [th.get("scope") for th in node.find("thead").find_all("th")] == ["col"] * 12
    assert [tr.find("th").get("scope") for tr in node.find("tbody").find_all("tr")] == ["row"] * 4
    assert list(body) == ["AC", "Stamina", "Hit points", "Weight (stone)"]
    assert body["AC"] == ["30", "33", "36", "39", "42", "45", "48", "51", "54", "57", "60"]
    assert node.find("caption").text() != "" and all(len(cells) == 11 for cells in body.values())


def test_every_figure_of_every_table_of_tiers_on_the_site_is_at_tier_s(built, table, records):
    rules = rules_module.load(RULES)
    shown = 0
    for key in build.item_page_keys(table):
        original = browser.item_to_catalog(records[key], table["defaults"])
        expected = expected_rows(original, rules)
        html = item_html(built.out, key)
        if not expected:
            assert html.find_all("table", id_="tiers") == [], key
            continue
        _, head, body = table_of(html, "tiers")
        assert head == ["Stat", *(f"+{tier}" for tier in TIERS)], key
        labels = {view.STAT_LABELS[k]: values for k, values in expected.items()}
        assert {label: [number(c) for c in cells] for label, cells in body.items()} == labels, key
        shown += 1
    assert shown == 47


def test_a_weapon_has_a_second_table_with_its_damage_and_delay_and_the_seal_of_the_weapon_rule(built):
    html = item_html(built.out, "w80524")  # a two-hander: 36 damage, a delay of 38
    _, head, body = table_of(html, "weapon-tiers")
    assert head == ["Stat", *(f"+{tier}" for tier in TIERS)]
    assert body["Damage"] == ["36", "39", "43", "46", "50", "54", "57", "61", "64", "68", "72"] and body["Delay"] == ["38"] * 11
    section = html.by_id("weapon")
    assert "2H Slashing" in section.text()
    link = next(a for a in section.find_all("a") if a.get("href") == "/rules/#tier.weapon_damage_pct")
    assert link.text() == "Weapon damage per tier"
    assert section.find(cls="seal-player") is not None and "open test" not in section.text()  # the seal; the rule is settled, so no test is open
    assert item_html(built.out, "w90001").find_all("table", id_="weapon-tiers") == []  # a helm has none
    assert item_html(built.out, "w80583").find_all("table", id_="weapon-tiers") == []  # nor has a shield


def test_the_stat_rules_are_linked_with_their_seals_under_the_table(built):
    html = item_html(built.out, "w90008")  # stats, haste and weight
    rules = html.by_id("tier-rules")
    hrefs = [a.get("href") for a in rules.find_all("a")]
    assert hrefs == ["/rules/#tier.stat_rule", "/rules/#haste.worn_per_tier", "/rules/#tier.weight_pct", "/rules/#tier.weight_floor"]
    assert len(rules.find_all(cls="seal")) == 4 and all(s.find("svg") is not None for s in rules.find_all(cls="seal"))
    assert "estimated" in rules.text()  # (said once: every figure is worked out)


def test_the_item_page_says_that_stats_and_weight_change_between_tiers_and_that_the_table_is_at_whole_tiers(built):
    note = "An item's stats and weight change gradually as it progresses toward its next tier. Each item is shown exactly at its tier."
    html = item_html(built.out, "w90008")
    section = html.by_id("stats-h").parent
    assert html.by_id("tier-progress").text() == note
    assert [p.get("id") for p in section.find_all("p")] == ["tier-rules", "tier-progress"]  # under the table, right after the rules its figures follow
    assert html.find("main").text().count(note) == 1
    assert html.by_id("tier-rules").text().count("estimated") == 1  # (the old line is as it was)


def test_the_table_of_tiers_scrolls_inside_its_own_region_and_is_reachable_by_keyboard(built):
    html = item_html(built.out, "w90001")
    region = html.by_id("tiers").parent
    assert region.has("tabindex") and region.get("tabindex") == "0" and region.get("role") == "region" and "scroll" in region.classes
    caption = html.by_id(region.get("aria-labelledby"))  # the region is named by the caption of its table, which the section round it is not named by
    assert caption.tag == "caption" and caption.parent is html.by_id("tiers") and caption.text() == "Stats of Helm of the Stoneward at each tier, +0 to +10"


def landmark_names(html) -> list[str]:
    """The accessible names of the region landmarks of a page, in page order: a section, or an element with the role region, that is named by ``aria-labelledby`` or ``aria-label``
    (one with no name is no landmark)."""
    names = []
    for node in html.find("main").iter():
        if node.tag == "section" or node.get("role") == "region":
            if node.get("aria-labelledby"):
                names.append(html.by_id(node.get("aria-labelledby").split()[0]).text())
            elif node.get("aria-label"):
                names.append(node.get("aria-label"))
    return names


def test_no_two_landmarks_of_an_item_page_have_the_same_name_the_section_and_the_scrolling_region_in_it_included(built, table):
    for key in build.item_page_keys(table):
        names = landmark_names(item_html(built.out, key))
        assert len(names) == len(set(names)), (key, names)  # (axe: landmark-unique)
    weapon = landmark_names(item_html(built.out, "w80524"))
    assert weapon[:4] == ["Stats by tier", "Stats of Gristmill Maul at each tier, +0 to +10", "Weapon", "Damage and delay of Gristmill Maul at each tier, +0 to +10"]
    assert landmark_names(item_html(built.out, "w90001"))[:2] == ["Stats by tier", "Stats of Helm of the Stoneward at each tier, +0 to +10"]


# ---- facts, sources, evidence, best for and the credit -----------------------------------------------------------------------------------


def test_the_sections_of_a_page_are_the_ones_the_page_promises_in_order(built):
    headings = lambda key: [h.text() for h in item_html(built.out, key).find("main").find_all("h2")]  # noqa: E731
    assert headings("w90001") == ["Stats by tier", "Sources", "Best for these trios", "Wiki credit"]  # (no section on the evidence level: wiki is the one level)
    assert headings("w80524") == ["Stats by tier", "Weapon", "Sources", "Best for these trios", "Wiki credit"]
    assert headings("w90046") == ["Stats by tier", "Sources", "Notes", "Best for these trios", "Wiki credit"]  # (an item with a note about it has that section)


def test_the_facts_sources_evidence_and_credit_are_in_the_page(built):
    html = item_html(built.out, "w90046")  # a chest piece for two deities, wiki level, dropped in The Hole
    main = html.find("main")
    facts = {dt.text(): dt.parent.find("dd").text() for dt in main.find_all("dt")}
    assert facts["Slot"] == "Chest" and facts["Classes"] == "All" and facts["Deity"] == "Needs deity: The Tribunal or Rodcet Nife" and facts["Weight"] == "6.0 stone"
    assert html.by_id("sources").text() == "Drops in: The Hole"
    assert not html.find_all("p", id_="level") and "Wiki evidence" not in html.find("main").text(skip_hidden=False)
    assert "Deity-locked" in html.by_id("notes").text() and html.by_id("notes").find(cls="seal-model") is not None
    credit = html.by_id("credit")
    revision = next(a for a in credit.find_all("a") if "oldid=" in a.get("href"))
    assert revision.get("href") == "https://eqlwiki.com/index.php?title=Mantle_of_the_Faithful&oldid=200045"
    assert "Mantle of the Faithful" in credit.text() and "200045" in credit.text()
    licence = next(a for a in credit.find_all("a") if a.text() == "CC BY-SA 4.0")
    assert licence.get("href") == "https://creativecommons.org/licenses/by-sa/4.0/legalcode"
    assert all(a.get("rel") == "noopener noreferrer" for a in credit.find_all("a"))


def test_an_item_page_says_nothing_of_an_evidence_level_whatever_the_level_of_the_item(built):
    for key in ("w90001", "w90046"):
        text = item_html(built.out, key).find("main").text(skip_hidden=False)
        assert "Seen in game" not in text and "Strict evidence" not in text and "Wiki evidence" not in text and "seen in game" not in text, key
    assert item_html(built.out, "w90040").by_id("sources").text() == "Drops in: Test Zone"  # a cap no kit wears has its page and its source all the same


def test_an_item_that_no_default_answer_wears_says_so_plainly_and_one_that_does_names_the_trio(built):
    worn = item_html(built.out, "w90001").by_id("best-for")
    assert [(a.get("href"), a.text()) for a in worn.find_all("a")] == [("/trio/pal-mnk-ber/", "Paladin / Monk / Berserker")]
    assert item_html(built.out, "w90001").find_all(None, id_="best-more") == []
    none = item_html(built.out, "w90040")  # a cap for wizards
    assert none.by_id("best-none").text() == "No trio's default answer wears this item."
    assert none.find_all("ul", id_="best-for") == []


# ---- text from the wiki and the catalog is escaped ------------------------------------------------------------------------------------------


HOSTILE_NAME = "<script>alert('name')</script> & \"Cap\" <b>of</b> 'Doom'"
HOSTILE_ZONE = "Plane <i>of</i> Hate & \"Fear\" <img src=x onerror=alert(1)>"
HOSTILE_QUEST = "The <u>Quest</u> & the \"Label\" <a href=\"javascript:alert(1)\">x</a>"
HOSTILE_TITLE = "Cap <svg onload=alert(1)> & \"Doom\""


@pytest.fixture(scope="module")
def variant(tmp_path_factory):
    """The fixture built with records changed: the cap no kit wears (a name, sources, a quest and a wiki title full of marks, quotes and ampersands, and the reasons of a hidden item
    on a strict one), a steel cap with no source at all, a weapon with no skill and a ring with no stat. The table's name, slots, tier rule, deity and level of an item a kit wears are held to the shards, so these two are free to change."""
    need_node()
    tmp = tmp_path_factory.mktemp("variant")
    results = tmp / "results"
    shutil.copytree(RESULTS, results)
    changed = json.loads((results / "items.json").read_text(encoding="utf-8"))
    by_key = {browser.record_key(r): r for r in changed["items"]}
    record = by_key["w90040"]
    record["name"] = HOSTILE_NAME
    record["source"] = {
        "drops": [HOSTILE_ZONE, HOSTILE_ZONE + " b", HOSTILE_ZONE + " c"], "sold": [HOSTILE_ZONE + " 2"], "forage": [HOSTILE_ZONE + " 3"],
        "quests": [HOSTILE_QUEST], "more": {"drops": 1},
    }  # fmt: skip
    # a seen flag made the cap strict, and the table still carries the reasons the public catalog hid it for, beside a note about the item
    record["evidence"] = {"level": "strict", "codes": ["cultural-container", "out-of-era", "zones-not-in-eql", "not-for-bis"]}
    del by_key["w90002"]["source"]
    by_key["w90002"]["weapon"] = {"skill": None, "dmg": 10, "delay": 20, "bonus": None}  # a weapon the page does not name a skill of
    by_key["w90027"]["stats"] = {}  # a ring with no stat and no weight
    by_key["w90027"]["weight10"] = None
    (results / "items.json").write_text(json.dumps(changed), encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["items"]["w90040"]["title"] = HOSTILE_TITLE
    changed_manifest = tmp / "manifest.json"
    changed_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    out = tmp / "dist"
    run_build(out, tmp, results=results, sources_manifest=changed_manifest)
    return SimpleNamespace(out=out, raw=read(out, "item/w90040/index.html"))


def test_the_name_the_sources_the_quest_and_the_wiki_title_of_a_page_are_text_whatever_marks_they_hold(variant):
    html = parse(variant.raw)
    assert [h.text() for h in html.find_all("h1")] == [HOSTILE_NAME]
    assert html.find("title").text() == f"{HOSTILE_NAME} · TrioForge"
    assert HOSTILE_NAME in html.find("meta", name="description").get("content")
    lines = [li.text() for li in html.by_id("sources").find_all("li")]
    for line in (f"Drops in: {HOSTILE_ZONE}, {HOSTILE_ZONE} b, {HOSTILE_ZONE} c and 1 more", f"Quests: {HOSTILE_QUEST}", f"Vendors in: {HOSTILE_ZONE} 2", f"Foraged in: {HOSTILE_ZONE} 3"):
        assert line in lines, line
    assert HOSTILE_TITLE in html.by_id("credit").text()
    # and nothing it holds became an element: the page has the scripts, the images and the elements of the template, and no others
    assert [(s.get("src") or "").split("-")[0] for s in html.find_all("script")] == ["/assets/boot", "/assets/app"]
    assert html.find_all("img") == [] and html.find_all("u") == [] and html.find_all("i") == [] and html.find_all("b") == [] and html.find_all("svg", onload=True) == []
    outside = [a.get("href") for a in html.find("main").find_all("a") if not a.get("href").startswith(("/", "https://eqlwiki.com/", "https://creativecommons.org/"))]
    assert outside == []  # (no link made of the quest's markup)


def test_the_page_of_an_item_that_a_seen_flag_made_strict_shows_the_note_about_the_item_and_none_of_the_reasons_it_was_hidden_for_nor_its_level(variant):
    html = parse(variant.raw)
    assert "Seen in game" not in variant.raw and "Strict evidence" not in variant.raw and not html.find_all("p", id_="level")
    notes = [li.text() for li in html.by_id("notes").find_all("li")]
    assert len(notes) == 1 and notes[0].startswith("Model") and "not used for best-in-slot" in notes[0]
    for code in ("cultural-container", "out-of-era", "zones-not-in-eql"):
        assert code not in variant.raw, code  # the code is not in the page, in any place
    assert "Note:" not in variant.raw


def test_in_the_html_of_the_page_every_mark_of_that_text_is_a_character_reference(variant):
    raw = variant.raw
    for marks in ("<script>alert", "<img", "<svg onload", "<u>", "<i>", "<b>", "<a href=\"javascript"):
        assert marks not in raw, marks
    assert "&lt;script&gt;alert(&#39;name&#39;)&lt;/script&gt; &amp; &#34;Cap&#34; &lt;b&gt;of&lt;/b&gt; &#39;Doom&#39;" in raw
    assert "&lt;a href=&#34;javascript:alert(1)&#34;&gt;x&lt;/a&gt;" in raw
    # the address of the wiki revision carries the title percent-encoded, and the report link carries the name the same way
    assert "title=Cap_%3Csvg_onload%3Dalert%281%29%3E_%26_%22Doom%22&amp;oldid=" in raw
    assert "%3Cscript%3Ealert" in raw


def changed_results(tmp_path: Path, key: str, **fields) -> Path:
    """A copy of the fixture's results in which the record of ``key`` has the given fields."""
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    changed = json.loads((results / "items.json").read_text(encoding="utf-8"))
    record = next(r for r in changed["items"] if browser.record_key(r) == key)
    record.update(fields)
    (results / "items.json").write_text(json.dumps(changed), encoding="utf-8")
    return results


def test_a_code_the_ladder_does_not_give_stops_the_build_naming_the_item_and_never_reaches_a_page(tmp_path):
    need_node()
    results = changed_results(tmp_path, "w90040", evidence={"level": "strict", "codes": ["a-code-from-the-future"]})
    with pytest.raises(build.BuildError, match=r"w90040.*a-code-from-the-future|a-code-from-the-future.*w90040"):
        run_build(tmp_path / "dist", tmp_path, results=results)
    assert not (tmp_path / "dist").exists()


def test_a_code_on_an_item_that_has_no_page_is_not_read_because_nothing_of_it_is_shown(tmp_path):
    need_node()
    results = changed_results(tmp_path, "w90041", evidence={"level": "hidden", "codes": ["a-code-from-the-future"]})  # the hidden helm
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=results, noindex=True)
    assert "item/w90041/index.html" not in item_files(out) and len(item_files(out)) == 47


def test_a_weapon_with_no_skill_in_the_table_says_so_and_a_bonus_that_is_not_there_is_not_shown(variant):
    section = item_html(variant.out, "w90002").by_id("weapon")
    assert [(dt.text(), dt.parent.find("dd").text()) for dt in section.find_all("dt")] == [("Skill", "not listed")]
    assert [tr.find("th").text() for tr in section.find("tbody").find_all("tr")] == ["Damage", "Delay"]


def test_an_item_with_no_stat_and_no_weight_has_no_table_of_tiers_and_says_so(variant):
    html = item_html(variant.out, "w90027")
    assert html.find_all("table", id_="tiers") == [] and html.find_all(None, id_="tier-rules") == []
    assert html.by_id("no-stats").text() == "No stat or weight is listed for this item."
    assert [h.text() for h in html.find("main").find_all("h2")][:2] == ["Stats by tier", "Sources"]


def test_an_item_with_no_source_in_the_table_says_so_and_has_no_list(variant):
    html = item_html(variant.out, "w90002")
    assert html.find_all("ul", id_="sources") == []
    assert html.by_id("sources-none").text() == "The item table lists no source for this item."
    assert "No source is known" not in variant.raw


def test_the_template_of_an_item_page_turns_no_escaping_off_and_has_no_script_or_style_of_its_own():
    path = REPO / "pipeline" / "trioforge" / "site" / "templates" / "item.html.j2"
    text = path.read_text(encoding="utf-8")
    assert "|safe" not in text and "| safe" not in text and "autoescape" not in text and "Markup" not in text
    assert not re.search(r"<script(?![^>]*\bsrc=)", text) and not re.search(r"\sstyle=|<style|\son[a-z]+=", text)


def test_the_rule_links_of_the_item_pages_name_rules_that_the_rules_page_has(built, table):
    ids = {node.get("id") for node in page(built.out, "rules/index.html").iter() if node.has("id")}
    checked = 0
    for key in build.item_page_keys(table):
        for anchor in item_html(built.out, key).find_all("a"):
            href = anchor.get("href")
            if href.startswith("/rules/#"):
                assert href.split("#")[1] in ids, (key, href)
                checked += 1
    assert checked > 47  # (a page has the stat rule at least, and the footer's level rule is on every page besides)


# ---- links to a page ------------------------------------------------------------------------------------------------------------------------


def kit_links(out: Path):
    rows = page(out, "trio/pal-mnk-ber/index.html").by_id("kit-body").find_all("tr")
    return [(tr.find(data_f="name"), tr.find(data_f="name").find_all("a")) for tr in rows]


def test_the_item_names_of_the_trio_page_link_to_the_pages_that_exist_and_an_empty_place_does_not(built, table):
    names = {r["name"]: browser.record_key(r) for r in table["items"]}
    pages = set(build.item_page_keys(table))
    linked = 0
    for name_node, anchors in kit_links(built.out):
        name = name_node.text()
        if name == "Leave empty":
            assert anchors == []
            continue
        key = names[name]
        assert key in pages and [a.get("href") for a in anchors] == [f"/item/{key}/"] and anchors[0].text() == name
        assert (built.out / "item" / key / "index.html").is_file()
        linked += 1
    assert linked == 21
    main = page(built.out, "trio/pal-mnk-ber/index.html").find("main")
    assert main.get("data-items") == "/item/"  # the page code links the names it paints by this address


def test_a_name_is_plain_text_where_the_item_has_no_page_a_disputed_one_and_a_hidden_one(table):
    results = data.load_trio(RESULTS / "pal-mnk-ber")
    changed = json.loads(json.dumps(table))
    by_key = {browser.record_key(r): r for r in changed["items"]}
    by_key["w90001"]["evidence"] = {"level": "disputed", "codes": ["out-of-era-tag-live-zone"]}  # the helm of the default kit
    by_key["w90003"]["evidence"] = {"level": "hidden"}
    by_key["w90003"]["owned_only"] = True
    pages = frozenset(build.item_page_keys(changed))
    assert "w90001" not in pages and "w90003" not in pages and "w90002" in pages
    strict = results.shards[("strict", "own")].scenario("OGR", "balanced", 4, "dw")
    rows = view.kit_rows(strict, pages)
    assert rows[0].name == "Helm of the Stoneward" and rows[0].href is None  # disputed: plain text
    assert all(row.href is None for row in rows if row.empty) and sum(1 for row in rows if row.href) == 20
    wiki = results.shards[("wiki", "own")]
    scenario = next(s for s in wiki.scenarios if any(i is not None and i.key == "w90003" for i in s.kit))
    crown = next(row for row, item in zip(view.kit_rows(scenario, pages), scenario.kit) if item is not None and item.key == "w90003")
    assert crown.href is None  # hidden: plain text
    assert view.kit_rows(strict, None)[0].href is None  # no pages given, no link (the page of a build that made none)
    assert view.kit_rows(strict, pages | {"w90001"})[0].href == "/item/w90001/"


def test_a_trio_page_that_can_show_an_item_with_no_page_is_an_error_naming_the_trio_and_the_item_and_not_a_page_without_links(table):
    """The page code links the names it paints by one base, which is only right when every item the page can show has a page; kits hold strict and wiki wearables only, so it
    holds. When it fails, the page must not quietly lose every link."""
    results = data.load_trio(RESULTS / "pal-mnk-ber")
    book = content.load_rulebook(RULES)
    caps = view.trio_caps(results.meta.trio, results.meta.level, rules_module.load(RULES))
    pages = frozenset(build.item_page_keys(table))
    shown = {item.key for item in data.used_items(results)}
    assert shown <= pages and "w90001" in shown
    assert view.trio_page(results, book, caps, pages).items_base == "/item/"
    assert view.trio_page(results, book, caps).items_base == ""  # (no pages given: no link, as the page of a build that made none)
    with pytest.raises(ValueError, match=r"pal-mnk-ber.*w90001|w90001.*pal-mnk-ber") as raised:
        view.trio_page(results, book, caps, pages - {"w90001"})
    assert "has no page" in str(raised.value)


def test_a_build_whose_item_pages_lack_an_item_that_a_trio_page_shows_is_refused_naming_the_trio_and_the_item(tmp_path, monkeypatch):
    need_node()
    real = build.item_page_keys
    monkeypatch.setattr(build, "item_page_keys", lambda table: [key for key in real(table) if key != "w90001"])
    with pytest.raises(build.BuildError, match=r"pal-mnk-ber.*w90001|w90001.*pal-mnk-ber"):
        run_build(tmp_path / "dist", tmp_path)
    assert not (tmp_path / "dist").exists()  # nothing was written


def shown_keys() -> set[str]:
    """The keys of the items that the trio pages of the fixture show: those of its kits and of its runner-ups."""
    results = data.load_trio(RESULTS / "pal-mnk-ber")
    return {i.key for s in results.shards.values() for i in s.items} | {i.key for i in results.runnerups.items}


def test_the_sources_page_lists_the_items_the_trio_pages_show_as_it_did_and_links_each_to_its_page(built, table):
    html = page(built.out, "sources/index.html")
    rows = html.by_id("revisions").find("tbody").find_all("tr")
    pages, shown = set(build.item_page_keys(table)), shown_keys()
    assert "w90040" in pages and "w90040" not in shown and len(shown) == 46  # the cap for wizards has a page, and no trio page shows it ...
    assert sorted(row.find("code").text() for row in rows) == sorted(shown)  # ... so the sources page does not list it: it lists the items it listed before the item pages
    for row in rows:
        key = row.find("code").text()
        anchors = row.find("th").find_all("a")
        assert key in pages and [a.get("href") for a in anchors] == [f"/item/{key}/"], key
        assert (built.out / "item" / key / "index.html").is_file()
    assert html.by_id("revisions-box").find("summary").text() == f"Pages and revisions used ({len(shown)})"
    assert "Cap of the Archmage" not in html.by_id("revisions").text()


def test_the_sources_page_says_that_each_item_page_carries_its_own_credit_and_its_description_is_of_the_items_shown(built):
    html = page(built.out, "sources/index.html")
    text = html.find("main").text()
    assert "Each item page carries its own credit: the wiki page, its revision, the licence and the changes made." in text
    assert "behind every item on this site" not in text and "each item on the site" not in text  # (the list is of the items the trio pages show, and the sentence says so)
    assert "the pages and revisions behind the items that the trio pages show are listed below" in text
    description = html.find("meta", name="description").get("content")
    assert description == "Where the data comes from, its licences and the wiki revision of every item shown."


def test_two_items_that_share_a_name_get_titles_that_differ_and_the_others_keep_theirs(tmp_path):
    need_node()
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    changed = json.loads((results / "items.json").read_text(encoding="utf-8"))
    by_key = {browser.record_key(r): r for r in changed["items"]}
    by_key["w90040"]["name"] = by_key["w90001"]["name"]  # the cap no kit wears is called what the helm of the default kit is called
    (results / "items.json").write_text(json.dumps(changed), encoding="utf-8")
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=results)
    titles = {key: item_html(out, key).find("title").text() for key in build.item_page_keys(changed)}
    assert titles["w90001"] == "Helm of the Stoneward (w90001) · TrioForge" and titles["w90040"] == "Helm of the Stoneward (w90040) · TrioForge"
    assert titles["w90002"] == "Steel Cap of Valor · TrioForge"  # a name that is nobody else's is the title as it was
    assert len(set(titles.values())) == len(titles) == 47  # every page has a title of its own
    assert [h.text() for h in item_html(out, "w90001").find_all("h1")] == ["Helm of the Stoneward"]  # (the name is the name)


def test_a_row_of_the_sources_page_is_plain_text_where_the_item_has_no_page():
    manifest = content.Manifest("a", "b", (), {"w1": ("One", 11), "w2": ("Two", 22), "w3": ("Three", 33)})
    rows = build.revision_rows(["w1", "w2", "w3"], manifest, frozenset({"w1", "w3"}))
    assert [(r.key, r.title, r.revid, r.page) for r in rows] == [("w1", "One", 11, "/item/w1/"), ("w3", "Three", 33, "/item/w3/"), ("w2", "Two", 22, None)]
    assert rows[0].url == content.wiki_url("One", 11)


def test_the_links_of_the_names_are_the_only_addresses_of_items_in_the_trio_page_but_the_one_its_code_paints_with(built):
    html = read(built.out, "trio/pal-mnk-ber/index.html")
    plain = re.sub(r'<a href="/item/[a-z0-9-]+/">([^<]*)</a>', r"\1", html)
    assert plain.count("/item/") == 1 and 'data-items="/item/"' in plain
    assert len(page(built.out, "trio/pal-mnk-ber/index.html").by_id("kit-body").find_all("tr")) == 22


def test_every_link_of_every_page_of_the_site_that_goes_to_an_item_goes_to_a_page_that_exists(built):
    checked = 0
    for path in sorted(built.out.rglob("*.html")):
        for anchor in parse(path.read_text(encoding="utf-8")).find_all("a"):
            href = anchor.get("href") or ""
            if href.startswith("/item/"):
                assert re.fullmatch(r"/item/[a-z0-9][a-z0-9-]{0,99}/", href), href
                assert (built.out / href.lstrip("/") / "index.html").is_file(), (path.name, href)
                checked += 1
    assert checked > 21


# ---- the trios that an item is best for, in a build of many -------------------------------------------------------------------------------------


def valid_trios(count: int) -> list[str]:
    """The fixture's own slug and ``count - 1`` other trios whose default answer (the fixture's: an Ogre, a Troll behind it) the build accepts: the race must be the creation-legal one with the
    highest value, and which races a trio can start depends on its classes."""
    results = data.load_trio(RESULTS / "pal-mnk-ber")
    found = []
    for trio in combinations(CLASS_CODES, 3):
        slug = "-".join(code.lower() for code in trio)
        if slug == "pal-mnk-ber":
            continue
        try:
            build.check_defaults(dataclasses.replace(results, meta=dataclasses.replace(results.meta, slug=slug, trio=trio)))
        except build.BuildError:
            continue
        found.append(slug)
    return ["pal-mnk-ber", *found[: count - 1]]


def many_trios(root: Path, slugs: list[str]) -> Path:
    scratch = root / "results"
    shutil.copytree(RESULTS, scratch)
    for slug in slugs[1:]:
        folder = scratch / slug
        shutil.copytree(scratch / slugs[0], folder)
        codes = [code.upper() for code in slug.split("-")]
        for path in folder.rglob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            if path.name == "engine-l50.json":
                document["trio"] = document["profile_common"]["trio"] = codes
            else:
                document["trio"] = slug
                if "classes" in document:
                    document["classes"] = codes
            path.write_text(json.dumps(document), encoding="utf-8")
        reindex(folder / "runnerups")
    return scratch


@pytest.fixture(scope="module")
def many(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("many")
    slugs = valid_trios(23)
    out = tmp / "dist"
    summary = run_build(out, tmp, results=many_trios(tmp, slugs), noindex=True)
    return SimpleNamespace(out=out, slugs=slugs, summary=summary)


def test_at_most_twenty_trios_are_named_in_the_order_of_their_slugs_and_the_others_are_counted(many):
    assert len(many.slugs) == 23
    html = item_html(many.out, "w90001")  # worn by the default answer of every one of the trios (the copies have the fixture's kit)
    links = html.by_id("best-for").find_all("a")
    assert [a.get("href") for a in links] == [f"/trio/{slug}/" for slug in sorted(many.slugs)[:20]]
    assert all((many.out / a.get("href").lstrip("/") / "index.html").is_file() for a in links)  # each is a page of the site
    assert html.by_id("best-more").text() == "and 3 more"
    assert item_html(many.out, "w90040").by_id("best-none").text() == "No trio's default answer wears this item."
    assert item_html(many.out, "w90040").find_all(None, id_="best-for") == []


# ---- budgets ---------------------------------------------------------------------------------------------------------------------------------


def test_a_page_that_names_twenty_trios_is_measured_and_is_within_the_budget(built, many):
    """The twenty links of Best for these trios are in the page, so they are in its size: the build of 23 trios has pages that name twenty, and they are larger than the pages of the build
    that names one, and within the limits."""
    sizes, one = many.summary.sizes, built.summary.sizes
    assert 0 < sizes["largest_item"] - one["largest_item"] < 3 * 1024  # about a link for each of nineteen more trios, 70 bytes each
    assert sizes["largest_item"] <= build.LIMITS["item_html"] and sizes["largest_item_gzip"] <= build.LIMITS["item_html_gzip"]


def test_an_item_page_has_16_kb_raw_and_4_kb_gzip(built, table):
    assert build.LIMITS["item_html"] == 16 * 1024 and build.LIMITS["item_html_gzip"] == 4 * 1024  # (raw: with twenty trios named the largest real pages reach 12.6 KB, and 12 KB left no room)
    sizes = [(len(raw := (built.out / f"item/{key}/index.html").read_bytes()), len(gzip.compress(raw, 9, mtime=0))) for key in build.item_page_keys(table)]
    assert max(r for r, _ in sizes) == built.summary.sizes["largest_item"] <= 16 * 1024
    assert max(g for _, g in sizes) == built.summary.sizes["largest_item_gzip"] <= 4 * 1024


def files_with_item_pages(sizes: dict[str, int]):
    first = ["assets/site-AAAAAAAA.css", "assets/boot-BBBBBBBB.js", "assets/app-CCCCCCCC.js"]
    files = {"trio/pal-mnk-ber/index.html": b"<html></html>", **{name: b"x" for name in first}}
    for key, size in sizes.items():
        files[f"item/{key}/index.html"] = (
            b'<link rel="stylesheet" href="/assets/site-AAAAAAAA.css"><script src="/assets/boot-BBBBBBBB.js"></script>'
            b'<script type="module" src="/assets/app-CCCCCCCC.js"></script>' + b"y" * size
        )
    return files, first


def check(files, first, items):
    return build.check_budgets(
        files, trio_pages=["trio/pal-mnk-ber/index.html"], first_load_assets={name: first for name in ["trio/pal-mnk-ber/index.html", *items]}, item_pages=items
    )


def test_the_budget_check_measures_the_item_pages_and_names_the_page_that_is_over(monkeypatch):
    files, first = files_with_item_pages({"w1": 1000, "w2": 5000})
    sizes = check(files, first, ["item/w1/index.html", "item/w2/index.html"])
    assert sizes["item_pages"] == 2 and 5000 < sizes["largest_item"] < 16 * 1024 and sizes["largest_item_gzip"] < 4 * 1024
    files, first = files_with_item_pages({"w1": 1000, "w2": 16 * 1024})
    with pytest.raises(build.BudgetError, match=r"item page item/w2/index.html is 16\.\d KB \(limit 16 KB\)"):
        check(files, first, ["item/w1/index.html", "item/w2/index.html"])


def test_the_budget_check_holds_the_gzip_size_of_an_item_page_apart_from_its_raw_size():
    import os

    files, first = files_with_item_pages({"w1": 0})
    files["item/w1/index.html"] += os.urandom(5000)  # bytes that do not compress: 5 KB raw and about as much gzipped
    with pytest.raises(build.BudgetError, match=r"item page item/w1/index.html is \d\.\d KB gzip \(limit 4 KB\)"):
        check(files, first, ["item/w1/index.html"])


def test_an_item_page_that_loads_any_file_but_the_page_script_the_boot_script_and_the_stylesheet_is_refused():
    files, first = files_with_item_pages({"w1": 100})
    files["assets/upgrade-input-DDDDDDDD.js"] = b"z"
    files["item/w1/index.html"] += b'<script type="module" src="/assets/upgrade-input-DDDDDDDD.js"></script>'
    with pytest.raises(build.BudgetError, match=r"item page item/w1/index.html loads /assets/upgrade-input-DDDDDDDD\.js"):
        check(files, first, ["item/w1/index.html"])
    files, first = files_with_item_pages({"w1": 100})
    files["item/w1/index.html"] += b"<script>alert(1)</script>"  # a script of its own
    with pytest.raises(build.BudgetError, match=r"item page item/w1/index.html has 3 scripts"):
        check(files, first, ["item/w1/index.html"])


def test_the_build_holds_its_item_pages_to_the_budget(tmp_path, monkeypatch):
    need_node()
    monkeypatch.setitem(build.LIMITS, "item_html", 2048)
    with pytest.raises(build.BudgetError, match=r"item page item/w\d+/index.html is \d+\.\d KB \(limit 2 KB\)"):
        run_build(tmp_path / "dist", tmp_path)
    assert not (tmp_path / "dist").exists()  # nothing was written


def test_an_item_page_loads_the_three_files_every_page_loads_and_nothing_else(built):
    trio = page(built.out, "trio/pal-mnk-ber/index.html")
    wanted = sorted(
        [l.get("href") for l in trio.find_all("link", rel="stylesheet")] + [s.get("src") for s in trio.find_all("script")]
    )
    assert len(wanted) == 3
    for key in ("w90001", "w80524", "w90040"):
        html = item_html(built.out, key)
        assert sorted([l.get("href") for l in html.find_all("link", rel="stylesheet")] + [s.get("src") for s in html.find_all("script")]) == wanted, key
        assert [s.get("type") for s in html.find_all("script")] == [None, "module"]


def test_the_command_line_reports_the_item_pages_with_the_largest_and_its_limits(tmp_path, capsys):
    need_node()
    code = build.main(["--results", str(RESULTS), "--out", str(tmp_path / "dist"), "--noindex", "--sources-manifest", str(MANIFEST)])
    assert code == 0
    line = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("item pages:"))
    assert re.fullmatch(r"item pages: 47, the largest \d+\.\d KB raw \(limit 16 KB\), \d+\.\d KB gzip \(limit 4 KB\)", line), line


def test_the_page_code_links_by_the_base_and_the_key_pattern_of_the_build():
    source = (REPO / "pipeline" / "trioforge" / "site" / "static" / "trio.js").read_text(encoding="utf-8")
    assert re.search(r'const ITEM_BASE = "([^"]*)";', source).group(1) == view.ITEM_BASE == "/item/"
    pattern = re.search(r"const ITEM_KEY = /\^(.*)\$/;", source).group(1)
    assert pattern == build._ITEM_KEY.pattern == data.KEY_PATTERN  # a key the build would refuse in an address is not put into one by the page code either
    assert re.fullmatch(pattern, "w90001") and not re.fullmatch(pattern, "W90001") and not re.fullmatch(pattern, "w1/../x")
    assert re.fullmatch(pattern, "r" + "a" * 100) and not re.fullmatch(pattern, "r" + "a" * 101)  # (as long as the reader of the results takes a key)


# ---- what DECISIONS says about the pages of the items ------------------------------------------------------------------------------------------


def test_decisions_records_what_gets_an_item_page_what_it_says_its_budgets_and_the_links_and_their_limits():
    text = " ".join((REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8").split())
    limits = build.LIMITS
    assert f"A page has {limits['item_html'] // 1024} KB raw and {limits['item_html_gzip'] // 1024} KB gzip" in text, "no decision line says what an item page may weigh (build.LIMITS refuses more)"
    for words in (
        "item_page_keys",  # what gets a page, and where the level comes from
        "never a private flag",
        "plain text where its item has no page",
        "at_tier",  # what the tables are
        "scrolls sideways inside its own region",  # why the table is not cards
        "named by the caption of its table",  # and what names the region
        "stylesheet, the boot script and the page script",  # what a page loads
        "view.EVIDENCE_CODES",  # the reasons of the evidence are never shown ...
        "view.ITEM_NOTES",  # ... and the notes about the item are, in words
        "stops the build",  # ... and a code the ladder does not give is not shown raw
        "data.KEY_PATTERN",  # one pattern of an item key
        "lists the items that the trio pages show, as before",  # what the sources page lists, and
        "carries its own credit",  # why it need not list more
        "do not link",  # the names that stay plain text, and why
        "Before and after",
    ):
        assert words in text, f"the decision about item pages does not say: {words}"
    line = next(line for line in (REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines() if line.startswith("- 2026-10-17 Item pages"))
    counts = [int(n.replace(",", "")) for n in re.findall(r"([0-9][0-9,]*) (?:pages|items|records|names)(?![a-z])", line)]
    assert counts and all(n < 100 for n in counts), "the decision line writes a count of pages or items of the real results (the fixture's are small; the flags decide the others)"


# ---- EQ Legends Tools (p7nek): an item read from that site says so, and the sources page names it ------------------------------------------------


def eqlt_build(tmp_path: Path):
    """A build in which the cap that no kit wears is an item of EQ Legends Tools with no wiki page (key rlt-moon-cap), and the first item is a wiki item that the site's tooltip overrides."""
    need_node()
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    changed = json.loads((results / "items.json").read_text(encoding="utf-8"))
    cap = next(r for r in changed["items"] if browser.record_key(r) == "w90040")
    cap["id"], cap["key"] = None, "rlt-moon-cap"
    cap["evidence"]["codes"] = ["source-eql-tools"]
    (results / "items.json").write_text(json.dumps(changed), encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    del manifest["items"]["w90040"]  # (the item has no wiki page)
    manifest["eqlegendstools"] = {"rlt-moon-cap": {"title": "Moon Cap", "slug": "moon-cap"}, "w90001": {"title": "Helm of the Stoneward", "slug": "helm-of-the-stoneward"}}
    edited = tmp_path / "manifest.json"
    edited.write_text(json.dumps(manifest), encoding="utf-8")
    out = tmp_path / "dist"
    run_build(out, tmp_path, results=results, sources_manifest=edited, noindex=True)
    return out


def test_an_item_read_from_eqlegendstools_has_a_source_credit_with_the_link_to_its_page_there_and_no_wiki_credit(tmp_path):
    out = eqlt_build(tmp_path)
    html = item_html(out, "rlt-moon-cap")
    assert [h.text() for h in html.find("main").find_all("h2")][-1] == "Source credit"
    assert html.find_all(None, id_="credit") == []  # (no wiki page to credit)
    (link,) = [a for a in html.by_id("origin").find_all("a")]
    assert link.get("href") == "https://eqlegendstools.com/items/moon-cap/" and link.text() == "EQ Legends Tools"
    assert "Stats and drop sources are read from the EQ Legends Tools page of the item" in read(out, "item/rlt-moon-cap/index.html")  # the evidence note, with its seal


def test_an_item_that_overrides_a_wiki_copy_keeps_the_wiki_credit_and_adds_the_source_credit(tmp_path):
    out = eqlt_build(tmp_path)
    html = item_html(out, "w90001")
    assert [h.text() for h in html.find("main").find_all("h2")][-2:] == ["Wiki credit", "Source credit"]
    assert html.by_id("credit") is not None and html.by_id("origin").find_all("a")[0].get("href") == "https://eqlegendstools.com/items/helm-of-the-stoneward/"
    assert item_html(out, "w90002").find_all(None, id_="origin") == []  # an item of the wiki alone has none


def test_the_sources_page_names_eqlegendstools_with_a_link_and_lists_its_items_and_the_wiki_attribution_is_as_it_was(tmp_path):
    out = eqlt_build(tmp_path)
    text = read(out, "sources/index.html")
    html = page(out, "sources/index.html")
    hrefs = {a.get("href") for a in html.find_all("a")}
    assert {"https://eqlegendstools.com/", "https://eqlegendstools.com/zones/nektropos-castle/", "https://eqlegendstools.com/items/moon-cap/"} <= hrefs
    assert "the source of the Nektropos Castle items" in text and "not covered by the wiki" in text
    rows = html.by_id("eqlt-items").find_all("tr")
    assert len(rows) == 3  # a header row and the two items
    assert build.ATTRIBUTION in text and text.count(build.ATTRIBUTION) == 1  # the wiki's attribution, word for word (and the footer's is the same text, in its own page element)
    assert "Item data adapted from eqlwiki.com (CC BY-SA 4.0) by the eqlwiki contributors" in text


def test_a_build_without_eqlegendstools_items_does_not_mention_it(tmp_path):
    need_node()
    out = tmp_path / "dist"
    run_build(out, tmp_path, noindex=True)
    assert "EQ Legends Tools" not in read(out, "sources/index.html") and "eqlegendstools" not in read(out, "item/w90001/index.html")
