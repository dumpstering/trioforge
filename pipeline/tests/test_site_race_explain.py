"""The trio page says what each close race gets you (race-explain): its value, what it changes in the kit's totals, its starting stats and its racial abilities; the sources page
credits the race pages the racials come from; and a row of "Wear this" shows the worn haste of its item without opening Stats.

Racial abilities are data for the page only. Nothing here changes the solve, the rules or which race is best: the model scores the Iksar's natural AC and no other racial, and the page
says which is which.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from site_helpers import parse
from test_site_build import need_node, read, run_build

from trioforge.site import build, content

REPO = Path(__file__).resolve().parents[2]
RACIALS = REPO / "derived" / "racials.json"


# ---- the credit on the sources page -----------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("race-explain")
    out = tmp / "dist"
    run_build(out, tmp, noindex=True)
    return out


def following(node, tag):
    """The first element of this tag after the node among its siblings."""
    siblings = node.parent.children
    return next(n for n in siblings[siblings.index(node) + 1 :] if not isinstance(n, str) and n.tag == tag)


def sources_page(out):
    return parse(read(out, "sources/index.html"))


def test_the_sources_page_credits_the_race_pages_the_racials_come_from(built):
    doc = sources_page(built)
    heading = next(h for h in doc.find_all("h2") if h.text() == "Racial abilities")
    paragraph = following(heading, "p")
    text = paragraph.text()
    assert "eqlwiki.com" in text and "CC BY-SA 4.0" in text and "by the eqlwiki contributors" in text
    assert "TrioForge's derived data from them is licensed the same way" in text  # share-alike, as for the items
    assert "only the Iksar's natural armour class is scored" in text
    hrefs = {a.get("href") for a in paragraph.find_all("a")}
    assert {"https://eqlwiki.com/", "https://creativecommons.org/licenses/by-sa/4.0/legalcode"} <= hrefs


def test_the_sources_page_lists_every_race_page_with_its_revision(built):
    doc = sources_page(built)
    box = doc.by_id("races-box")
    racials = content.load_racials(RACIALS)
    rows = box.find("tbody").find_all("tr")
    assert len(rows) == len(racials.pages) == 15
    assert box.find("summary").text() == "Race pages and revisions used (15)"
    ogre = next(row for row in rows if row.find("th").text() == "Ogre")
    link = ogre.find("a")
    assert link.get("href") == "https://eqlwiki.com/index.php?title=Ogre&oldid=153426" and link.text() == "153426" and link.get("rel") == "noopener noreferrer"
    assert ogre.find("code").text() == "OGR"
    assert [r.find("code").text() for r in rows] == [p.race for p in racials.pages]


def test_the_data_inputs_of_the_sources_page_name_the_race_pull_and_its_date(built):
    doc = sources_page(built)
    inputs = [li.text() for li in doc.find_all("li") if "Category:Character_Races" in li.text()]
    assert inputs == ["https://eqlwiki.com/index.php?title=Category:Character_Races, 2026-11-08"]


def test_the_footer_attribution_of_the_items_is_what_it_was(built):
    """The one attribution text of the site (footer, data files, LICENSE-DATA) is about the items; the racials are credited where they are shown."""
    assert build.ATTRIBUTION.startswith("Item data adapted from eqlwiki.com (CC BY-SA 4.0) by the eqlwiki contributors; quest giver data compiled by EQL Tools")


# ---- the build reads derived/racials.json -----------------------------------------------------------------------------------------


def test_a_missing_racials_file_stops_the_build_with_one_line_that_names_the_option(tmp_path):
    need_node()
    with pytest.raises(content.ContentError) as caught:
        run_build(tmp_path / "dist", tmp_path, noindex=True, racials=tmp_path / "nothing.json")
    assert "--racials" in str(caught.value) and "\n" not in str(caught.value)


def test_a_racials_file_that_is_not_what_the_writer_makes_stops_the_build(tmp_path):
    need_node()
    broken = tmp_path / "racials.json"
    document = json.loads(RACIALS.read_text(encoding="utf-8"))
    document["license"] = "MIT"
    broken.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(content.ContentError, match="licence"):
        run_build(tmp_path / "dist", tmp_path, noindex=True, racials=broken)


def test_the_command_line_takes_the_racials_file(tmp_path, capsys):
    need_node()
    from test_site_build import MANIFEST, RESULTS, make_changelog

    out = tmp_path / "dist"
    arguments = ["--results", str(RESULTS), "--out", str(out), "--noindex", "--sources-manifest", str(MANIFEST), "--changelog", str(make_changelog(tmp_path))]
    copy = tmp_path / "other-racials.json"
    shutil.copy(RACIALS, copy)
    assert build.main([*arguments, "--racials", str(copy)]) == 0
    assert build.main([*arguments, "--racials", str(tmp_path / "missing.json")]) == 2
    assert "--racials" in capsys.readouterr().err
