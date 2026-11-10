"""Racial abilities from the race pages of eqlwiki: the parser, the file it writes (``derived/racials.json``) and the site's reader of it.

The parser is tested on two recorded pages (``fixtures/wiki-races``: Ogre and Iksar) and on small invented ones; nothing here asks the network.
Racial abilities are data for the trio page only: nothing in the solve, the rules or the results reads them.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from trioforge.data import races as races_module
from trioforge.data.jsonio import load_strict
from trioforge.site import content
from trioforge.sources import eqlwiki, racials

REPO = Path(__file__).resolve().parents[2]
PAGES = REPO / "fixtures" / "wiki-races"
COMMITTED = REPO / "derived" / "racials.json"


def page(name: str) -> dict:
    return json.loads((PAGES / f"{name}.json").read_text(encoding="utf-8"))


def invented(title: str, text: str, *, revid: int = 4242, pageid: int = 900) -> dict:
    return {"pageid": pageid, "ns": 0, "title": title, "revid": revid, "timestamp": "2026-11-01T00:00:00Z", "content": text}


def racial_page(*items: str, sections: str = "") -> str:
    return f"==Basic Information==\n*<b>Racial(s):</b> {', '.join(items)}\n*<b>Starting City:</b> Nowhere\n\n==Base Stats==\n| 1 || 2\n\n{sections}\n{{{{Navbox Race}}}}\n"


def parsed(record: dict) -> racials.RacePage:
    result = racials.parse_page(record)
    assert isinstance(result, racials.RacePage), result
    return result


# ---- the Ogre page ----------------------------------------------------------------------------------------------------------------


def test_the_ogre_page_gives_its_four_racials_in_the_order_the_page_lists_them():
    result = parsed(page("ogre"))
    assert result.code == "OGR" and result.title == "Ogre" and result.revid == 153426
    assert [r["name"] for r in result.rows] == ["Increased Consumption Rate", "Infravision", "Frontal Stun Immunity", "Slam"]


def test_a_racial_with_a_section_is_described_by_the_first_sentence_of_the_section():
    rows = {r["name"]: r["description"] for r in parsed(page("ogre")).rows}
    assert rows["Frontal Stun Immunity"] == "Ogres cannot be stunned from the front, which gives them a great advantage over other races."
    assert rows["Increased Consumption Rate"] == "Barbarians, Halflings, Ogres, and Trolls all consume food and drink slightly faster than other races."
    assert rows["Infravision"] == "Slightly improved night vision, not as good as the Dark Elf's Ultravision."  # links become their labels


def test_a_racial_with_no_section_is_described_by_its_name_in_the_list():
    rows = {r["name"]: r["description"] for r in parsed(page("ogre")).rows}
    assert rows["Slam"] == "Slam"  # the page says nothing more of it, and nothing more is made up


def test_every_row_names_the_page_and_the_revision_it_was_read_from():
    for row in parsed(page("ogre")).rows:
        assert row["race"] == "OGR" and row["revid"] == 153426
        assert row["source"] == "https://eqlwiki.com/index.php?title=Ogre&oldid=153426"
        assert set(row) == {"race", "name", "description", "source", "revid"}


# ---- the Iksar page ---------------------------------------------------------------------------------------------------------------


def test_the_iksar_page_gives_its_seven_racials_with_their_figures_and_signs():
    rows = parsed(page("iksar")).rows
    assert [r["name"] for r in rows] == [
        "Forage", "Increased Armor Class", "Increased HP Regeneration", "Infravision", "Swimming (100)", "-10 Cold Resist", "+5 Fire Resist",
    ]  # fmt: skip
    assert {r["race"] for r in rows} == {"IKS"}


def test_the_iksar_armour_class_racial_keeps_the_wikis_own_sentence():
    rows = {r["name"]: r["description"] for r in parsed(page("iksar")).rows}
    assert rows["Increased Armor Class"] == "Iksar start with a +15 AC bonus (+17 if they are a Warrior) over other races, which scales(!) with level."


def test_a_sentence_that_introduces_a_table_loses_its_colon():
    rows = {r["name"]: r["description"] for r in parsed(page("iksar")).rows}
    assert rows["Increased HP Regeneration"] == "Both Iksar and Trolls have higher HP regeneration rates (per tick)"


def test_a_resist_racial_and_a_linked_skill_with_no_section_are_described_by_their_names():
    rows = {r["name"]: r["description"] for r in parsed(page("iksar")).rows}
    assert rows["-10 Cold Resist"] == "-10 Cold Resist" and rows["Swimming (100)"] == "Swimming (100)" and rows["Forage"] == "Forage"


# ---- the shapes of the other pages ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "code"),
    [("Ogre", "OGR"), ("High Elf", "HIE"), ("Wood Elf", "ELF"), ("Half-Elf", "HEF"), ("Kerra", "KER"), ("Froglok", "FRG"), ("Dark Elf", "DEF")],
)
def test_a_page_title_is_matched_to_its_race_code_by_the_name_the_rules_use(title, code):
    assert parsed(invented(title, racial_page("Infravision"))).code == code


def test_a_race_the_rules_have_no_code_for_is_skipped_and_says_why():
    skipped = racials.parse_page(invented("Half Dark Elf", racial_page("Infravision")))
    assert isinstance(skipped, racials.Skip) and skipped.reason == "no-race-code" and skipped.title == "Half Dark Elf"


def test_every_race_of_the_rules_has_a_title_that_matches_it():
    titles = {racials.race_code(name) for name in ("Human", "Barbarian", "Erudite", "Wood Elf", "High Elf", "Dark Elf", "Half-Elf", "Dwarf", "Troll", "Ogre", "Halfling", "Gnome", "Iksar", "Kerra", "Froglok")}
    assert titles == set(races_module.RACE_NAMES)


def test_a_page_that_says_the_race_has_no_racials_has_none():
    assert parsed(invented("Human", racial_page("None"))).rows == []


def test_a_racial_is_found_whether_the_label_is_bold_in_html_or_in_wiki_marks():
    marked = "==Basic Information==\n* '''Racial(s):''' Increased Swimming, +15 Poison Resist\n"
    assert [r["name"] for r in parsed(invented("Froglok", marked)).rows] == ["Increased Swimming", "+15 Poison Resist"]


def test_a_comma_inside_a_link_or_a_bracket_does_not_split_a_racial():
    text = racial_page("[[Skill Tinkering|Tinkering, the skill]]", "Sense Heading (50, max)", "[[Hide]]")
    assert [r["name"] for r in parsed(invented("Gnome", text)).rows] == ["Tinkering, the skill", "Sense Heading (50, max)", "Hide"]


def test_a_section_is_found_whatever_the_case_the_spacing_and_the_figure_of_its_racial():
    sections = "==  sense   heading ==\nHalflings find their way. They are good at it.\n"
    rows = parsed(invented("Halfling", racial_page("[[Sense Heading]] (50)", sections=sections))).rows
    assert rows[0]["name"] == "Sense Heading (50)" and rows[0]["description"] == "Halflings find their way."


def test_the_section_runs_to_the_next_heading_and_its_first_paragraph_gives_the_sentence():
    sections = "==Infravision==\n\n\nFirst sentence here. Second sentence.\n\nA later paragraph.\n\n==Other==\nNot this one.\n"
    rows = parsed(invented("Gnome", racial_page("Infravision", "Other thing", sections=sections))).rows
    assert rows[0]["description"] == "First sentence here."
    assert rows[1]["description"] == "Other thing"  # no section of that name: "Other" is not "Other thing"


def test_a_sentence_ends_at_a_full_stop_before_a_capital_or_a_figure_and_not_inside_a_number():
    sections = "==Cursed==\n10% increased effectiveness of lifetaps. 20% reduced regeneration, 1.5 times as often. Then more.\n"
    assert parsed(invented("Gnome", racial_page("Cursed", sections=sections))).rows[0]["description"] == "10% increased effectiveness of lifetaps."


def test_a_page_with_no_racial_list_at_all_is_skipped_with_a_reason_of_its_own():
    """A page that has no "Racial(s):" line is not a page that says the race has none: it gives no row and no page, and says why in ``skipped`` (it was ``[]`` and no entry before)."""
    skipped = racials.parse_page(invented("Gnome", "==Description==\nA small race.\n"))
    assert isinstance(skipped, racials.Skip) and skipped.reason == "no-racial-list" and skipped.title == "Gnome"


@pytest.mark.parametrize("line", ["*<b>Racial(s):</b>", "* '''Racial(s):'''   ", "*<b>Racial(s):</b> ,  ,", "*<b>Racial(s):</b> <!-- none yet -->"])
def test_a_racial_line_with_nothing_after_its_label_is_no_list_either(line):
    skipped = racials.parse_page(invented("Gnome", f"==Basic Information==\n{line}\n*<b>Starting City:</b> Nowhere\n"))
    assert isinstance(skipped, racials.Skip) and skipped.reason == "no-racial-list"


def test_none_in_the_list_still_means_the_race_has_no_racials():
    for text in ("None", "none", "[[None]]", "None "):
        result = parsed(invented("Human", racial_page(text)))
        assert result.rows == [] and result.code == "HUM", text


# ---- hostile text -----------------------------------------------------------------------------------------------------------------


def test_the_text_is_made_safe_like_every_other_wiki_text_of_the_catalog():
    sections = "==Infravision==\nSee <script>alert(1)</script> http://example.invalid/x for www.example.invalid more.​ Next.\n"
    rows = parsed(invented("Gnome", racial_page("Infravision", sections=sections))).rows
    text = rows[0]["description"]
    assert "<" not in text and ">" not in text and "://" not in text and "www." not in text and "​" not in text
    assert len(text) <= 300


def test_a_description_longer_than_the_limit_is_cut():
    sections = "==Infravision==\n" + ("word " * 200) + ".\n"
    assert len(parsed(invented("Gnome", racial_page("Infravision", sections=sections))).rows[0]["description"]) <= 300


def test_a_page_with_too_many_unclosed_openers_is_skipped_and_not_parsed():
    text = racial_page("Infravision") + "{{a|" * 40
    skipped = racials.parse_page(invented("Gnome", text))
    assert isinstance(skipped, racials.Skip) and skipped.reason == "too-complex"


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        ({"pageid": 1, "ns": 0, "title": "Gnome", "revid": None, "content": None, "missing": True}, "missing"),
        (invented("Gnome", "#REDIRECT [[Somewhere]]"), "redirect"),
        (invented("Gnome", "   \n"), "empty"),
        ({**invented("Gnome", racial_page("Hide")), "ns": 1}, "namespace"),
        (invented("Gnome", "x" * 70_000), "too-large"),
    ],
)
def test_a_page_that_is_not_a_race_page_is_skipped_with_a_reason(record, reason):
    skipped = racials.parse_page(record)
    assert isinstance(skipped, racials.Skip) and skipped.reason == reason


def test_parse_page_never_raises_whatever_the_text():
    for text in ("[[", "{{", "==", "<b>Racial(s):</b>", "*<b>Racial(s):</b> ,,,", "\x00\x01", "Racial(s):" * 500):
        result = racials.parse_page(invented("Gnome", text))
        assert isinstance(result, (racials.RacePage, racials.Skip))


# ---- the snapshot, and the file made from it --------------------------------------------------------------------------------------


def make_snapshot(root: Path, records: list[dict], *, category: str = racials.CATEGORY, date: str = "2026-11-08") -> Path:
    """A finished fetch of ``records`` in the layout of :mod:`trioforge.sources.eqlwiki` (what ``fetch --category`` writes)."""
    raw = root / "raw"
    raw.mkdir(parents=True)
    ids = [record["pageid"] for record in records]
    members = {"category": category, "members": [{"pageid": r["pageid"], "title": r["title"]} for r in records]}
    eqlwiki._atomic_write(raw / "members.json", eqlwiki._json_bytes(members, indent=1))
    eqlwiki._write_batch(raw / "batch-0000.json.gz", 0, ids, records)
    manifest = {"date": date, "category": category, "members": len(ids), "batches": 1, "pages": len(ids), "missing": 0}
    eqlwiki._atomic_write(root / "manifest.json", eqlwiki._json_bytes(manifest, indent=1))
    return root


@pytest.fixture()
def snapshot(tmp_path):
    ogre, iksar = page("ogre"), page("iksar")
    human = invented("Human", racial_page("None"), revid=77, pageid=3)
    odd = invented("Half Dark Elf", racial_page("Infravision"), revid=88, pageid=4)
    return make_snapshot(tmp_path / "snap", [ogre, iksar, human, odd])


def test_the_file_has_the_pages_the_racials_and_what_was_skipped(snapshot):
    document = racials.read_racials(snapshot)
    assert [p["race"] for p in document["pages"]] == ["HUM", "OGR", "IKS"]  # in the order of the rules' codes
    ogre = next(p for p in document["pages"] if p["race"] == "OGR")
    assert ogre == {"race": "OGR", "title": "Ogre", "revid": 153426, "url": "https://eqlwiki.com/index.php?title=Ogre&oldid=153426"}
    assert [r["name"] for r in document["racials"] if r["race"] == "OGR"] == ["Increased Consumption Rate", "Infravision", "Frontal Stun Immunity", "Slam"]
    assert [r for r in document["racials"] if r["race"] == "HUM"] == []
    assert document["skipped"] == [{"title": "Half Dark Elf", "reason": "no-race-code"}]


def test_the_written_file_carries_the_licence_the_attribution_and_where_it_came_from(snapshot, tmp_path):
    out = tmp_path / "derived" / "racials.json"
    document = racials.write_racials(snapshot, out, "2026-11-08")
    written = load_strict(out)
    assert written == document
    assert list(written) == ["provenance", "license", "attribution", "pages", "racials", "skipped"]
    assert written["license"] == "CC BY-SA 4.0"
    assert "eqlwiki.com" in written["attribution"] and "CC BY-SA 4.0" in written["attribution"] and "changes:" in written["attribution"]
    inputs = written["provenance"]["inputs"]
    assert len(inputs) == 1 and inputs[0]["file"] == "https://eqlwiki.com/index.php?title=Category:Character_Races" and inputs[0]["date"] == "2026-11-08"
    assert len(inputs[0]["sha256"]) == 64
    assert written["provenance"]["generated"] == "2026-11-08" and written["provenance"]["generator"].startswith("trioforge.sources.racials ")


def test_the_same_snapshot_gives_the_same_bytes(snapshot, tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    racials.write_racials(snapshot, first, "2026-11-08")
    racials.write_racials(snapshot, second, "2026-11-08")
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().endswith(b"\n") and b"\r" not in first.read_bytes()


def test_a_snapshot_of_another_category_is_refused(tmp_path):
    other = make_snapshot(tmp_path / "items", [page("ogre")], category="Category:Items")
    with pytest.raises(ValueError, match="Category:Character Races"):
        racials.read_racials(other)


def test_a_snapshot_with_no_race_page_at_all_is_refused(tmp_path):
    empty = make_snapshot(tmp_path / "none", [invented("Half Dark Elf", racial_page("Infravision"))])
    with pytest.raises(ValueError, match="no race page"):
        racials.read_racials(empty)


def test_an_unfinished_snapshot_is_refused_with_one_line(tmp_path):
    with pytest.raises(ValueError) as caught:
        racials.read_racials(tmp_path / "nothing")
    assert "\n" not in str(caught.value)


def test_a_failed_write_leaves_the_old_file_as_it_was(snapshot, tmp_path):
    out = tmp_path / "racials.json"
    out.write_text("old\n", encoding="utf-8")
    broken = make_snapshot(tmp_path / "broken", [], category="Category:Items")
    with pytest.raises(ValueError):
        racials.write_racials(broken, out, "2026-11-08")
    assert out.read_text(encoding="utf-8") == "old\n"


def test_the_command_line_writes_the_file_and_says_what_it_made(snapshot, tmp_path, capsys):
    out = tmp_path / "out" / "racials.json"
    assert racials.main(["--wiki", str(snapshot), "--out", str(out), "--date", "2026-11-08"]) == 0
    assert "racials.json" in capsys.readouterr().out and out.is_file()


def test_the_command_line_ends_with_status_2_and_one_line_on_a_bad_snapshot(tmp_path, capsys):
    assert racials.main(["--wiki", str(tmp_path / "missing"), "--out", str(tmp_path / "x.json")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and len(err.strip().splitlines()) == 1
    assert not (tmp_path / "x.json").exists()


# ---- the site's reader ------------------------------------------------------------------------------------------------------------


@pytest.fixture()
def document(snapshot, tmp_path):
    return racials.write_racials(snapshot, tmp_path / "racials.json", "2026-11-08")


def write_doc(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "edited.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_the_reader_gives_the_racials_of_each_race_in_page_order(tmp_path, document):
    loaded = content.load_racials(tmp_path / "racials.json")
    assert [r.name for r in loaded.of("OGR")] == ["Increased Consumption Rate", "Infravision", "Frontal Stun Immunity", "Slam"]
    assert loaded.of("HUM") == () and loaded.of("TRL") == ()  # a race with no page or no racial has none
    assert loaded.page("OGR").revid == 153426 and loaded.page("OGR").url.endswith("oldid=153426") and loaded.page("TRL") is None
    assert loaded.license == "CC BY-SA 4.0" and "eqlwiki.com" in loaded.attribution


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.update(license="MIT"),
        lambda d: d.pop("attribution"),
        lambda d: d["racials"][0].update(race="ZZZ"),
        lambda d: d["racials"][0].update(revid="153426"),
        lambda d: d["racials"][0].update(source="https://example.invalid/page"),
        lambda d: d["racials"][0].update(name=""),
        lambda d: d["racials"][0].update(description=7),
        lambda d: d["racials"].append(copy.deepcopy(d["racials"][0])),
        lambda d: d["pages"].append(copy.deepcopy(d["pages"][0])),
        lambda d: d["racials"][0].update(race="HUM"),  # a racial of a race whose page says no
    ],
)
def test_the_reader_refuses_a_file_that_is_not_what_the_writer_makes(tmp_path, document, edit):
    edited = copy.deepcopy(document)
    edit(edited)
    with pytest.raises(content.ContentError) as caught:
        content.load_racials(write_doc(tmp_path, edited))
    assert "\n" not in str(caught.value) and "edited.json" in str(caught.value)


def test_the_reader_names_the_file_when_it_is_missing(tmp_path):
    with pytest.raises(content.ContentError) as caught:
        content.load_racials(tmp_path / "racials.json")
    assert "--racials" in str(caught.value) and "\n" not in str(caught.value)


# ---- the committed file -----------------------------------------------------------------------------------------------------------


def test_the_committed_file_is_read_by_the_site_and_has_a_page_for_every_race_of_the_rules():
    loaded = content.load_racials(COMMITTED)
    assert {p.race for p in loaded.pages} == set(races_module.RACE_NAMES)
    assert loaded.license == "CC BY-SA 4.0"


def test_the_committed_file_has_the_ogre_racials_the_brief_names_and_nothing_made_up():
    loaded = content.load_racials(COMMITTED)
    assert [r.name for r in loaded.of("OGR")] == ["Increased Consumption Rate", "Infravision", "Frontal Stun Immunity", "Slam"]
    slam = next(r for r in loaded.of("OGR") if r.name == "Slam")
    assert slam.description == "Slam"


def test_the_committed_file_holds_no_markup_and_no_address_in_a_description():
    for row in load_strict(COMMITTED)["racials"]:
        for field in ("name", "description"):
            assert not any(mark in row[field] for mark in ("<", ">", "[[", "]]", "{{", "}}", "://", "'''")), row


def test_the_committed_file_is_what_the_writer_makes_from_the_recorded_race_pages():
    """The two recorded pages of the fixtures give the rows the file holds for Ogre and Iksar, so a change of the parser shows here."""
    committed = load_strict(COMMITTED)
    for name, code in (("ogre", "OGR"), ("iksar", "IKS")):
        assert [r for r in committed["racials"] if r["race"] == code] == parsed(page(name)).rows


def test_the_races_snapshots_never_sit_where_the_item_tests_look_for_the_latest_pull():
    """pipeline/tests/test_catalog.py takes the last ``sources/eqlwiki/*/manifest.json`` for the pull of items: a race snapshot filed beside the item pulls would be taken for one."""
    for manifest in sorted((REPO / "sources" / "eqlwiki").glob("*/manifest.json")):
        assert json.loads(manifest.read_text(encoding="utf-8"))["category"] == "Category:Items", manifest.parent.name


# ---- the licence file credits them --------------------------------------------------------------------------------------------------


def test_the_data_licence_carries_the_attribution_of_the_racial_abilities_beside_that_of_the_items():
    """LICENSE-DATA covers derived/ and fixtures/: the racial abilities (derived/racials.json, fixtures/wiki-races) are the wiki's text, so the file that gives the attribution says so in the words the
    derived file carries itself, under the line about the items (which stays as it is: build.ATTRIBUTION, held by test_site_build)."""
    from trioforge.site import build

    text = (REPO / "LICENSE-DATA").read_text(encoding="utf-8")
    assert build.ATTRIBUTION in text and racials.ATTRIBUTION in text
    assert text.index(build.ATTRIBUTION) < text.index(racials.ATTRIBUTION)
    assert load_strict(COMMITTED)["attribution"] == racials.ATTRIBUTION
    assert "derived/racials.json" in text and "fixtures/wiki-races" in text


@pytest.mark.parametrize("race", [["OGR"], {"code": "OGR"}, None, 7, 1.5, True])
def test_a_page_or_a_racial_whose_race_is_not_text_is_a_content_error_and_never_a_type_error(tmp_path, document, race):
    """A race is a key of the rules' table of names: a value that cannot be one (a list cannot even be hashed) is the file's fault, said as the file's fault."""
    for where in ("pages", "racials"):
        edited = copy.deepcopy(document)
        edited[where][0]["race"] = race
        with pytest.raises(content.ContentError) as caught:
            content.load_racials(write_doc(tmp_path, edited))
        assert "\n" not in str(caught.value) and "edited.json" in str(caught.value)


@pytest.mark.parametrize("field", ["title", "name", "description", "source", "url"])
@pytest.mark.parametrize("value", [["x"], {"x": 1}, None, 7])
def test_no_other_field_of_a_row_that_is_not_text_gives_a_type_error_either(tmp_path, document, field, value):
    for where in ("pages", "racials"):
        if field not in document[where][0]:
            continue
        edited = copy.deepcopy(document)
        edited[where][0][field] = value
        with pytest.raises(content.ContentError):
            content.load_racials(write_doc(tmp_path, edited))


# ---- a page with no list of racials -------------------------------------------------------------------------------------------------


def test_a_page_with_no_racial_list_is_listed_in_skipped_and_has_no_page_or_row_in_the_file(tmp_path):
    no_list = invented("Gnome", "==Description==\nA small race.\n", revid=55, pageid=5)
    human = invented("Human", racial_page("None"), revid=77, pageid=3)
    document = racials.read_racials(make_snapshot(tmp_path / "snap", [page("ogre"), no_list, human]))
    assert {p["race"] for p in document["pages"]} == {"OGR", "HUM"}  # (Human says none: a page and no rows)
    assert document["skipped"] == [{"title": "Gnome", "reason": "no-racial-list"}]
    assert not [r for r in document["racials"] if r["race"] in ("GNM", "HUM")]


SNAPSHOT = REPO / "sources" / "eqlwiki" / "races" / "2026-11-08"


@pytest.mark.skipif(not (SNAPSHOT / "manifest.json").is_file(), reason="needs the race snapshot of 2026-11-08 (sources/eqlwiki/races, git-ignored)")
def test_the_committed_file_is_byte_for_byte_what_the_writer_makes_from_the_snapshot(tmp_path):
    out = tmp_path / "racials.json"
    racials.write_racials(SNAPSHOT, out, "2026-11-08")
    assert out.read_bytes() == COMMITTED.read_bytes()
