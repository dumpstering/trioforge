"""The catalog build with the EQ Legends Tools source (``--eqlegendstools``, p7nek)."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

import pytest
from test_catalog import DATE, build, items_by_key, level_and_codes, quests_file, read_json, synthetic_record  # noqa: F401 - (quests_file is a fixture)

from trioforge.data.catalog import ATTRIBUTION, BuildError, main, validate_catalog
from trioforge.sources import eqlegendstools as eqlt
from trioforge.sources.http import PoliteClient

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures" / "eqlegendstools"
PAGES = {
    "checkmate": (FIXTURES / "item-checkmate.html").read_text(encoding="utf-8"),
    "worn-great-blade": (FIXTURES / "item-worn-great-blade.html").read_text(encoding="utf-8"),
}
ZONE = '<html><body><a href="/items/checkmate/">Checkmate</a> <a href="/items/worn-great-blade/">Blade</a> <a href="/items/checkmate/">again</a></body></html>'


def snapshot(root: Path) -> Path:
    """A finished fetch of a zone page that lists two items, made by the fetcher itself on a fake transport."""
    pages = {eqlt.zone_url("nektropos-castle"): ZONE, **{eqlt.item_url(slug): html for slug, html in PAGES.items()}}

    def transport(url, headers):
        return 200, {}, gzip.compress(pages[url].encode("utf-8"))

    client = PoliteClient(eqlt.USER_AGENT, transport=transport, sleep=lambda s: None, clock=lambda: 0.0, min_interval=0, honour_robots=False)
    out = root / "2026-10-25"
    eqlt.run_fetch(client, out, date(2026, 10, 25), say=lambda text: None)
    return out


WIKI_CHECKMATE = synthetic_record(
    73036, "Checkmate", statsblock="Attunable<br>\nSlot: EAR<br>\nAC: 6<br>\nWIS: +8  MANA: +10<br>\nSize: TINY WT: 0.1<br>\nClass: WAR MNK ROG BER",
    dropsfrom="\n[[Nektropos Castle]]\n* [[The Game Master]]\n",
)


def test_the_site_item_overrides_the_wiki_copy_and_the_other_is_added_and_both_are_live(tmp_path, quests_file):  # noqa: F811
    folder = snapshot(tmp_path)
    summary, out = build(tmp_path, [WIKI_CHECKMATE], quests_file, eqlegendstools_dir=folder)
    document = read_json(out / "catalog.json")
    validate_catalog(document)
    items = items_by_key(out)
    assert sorted(items) == ["rlt-worn-great-blade", "w73036"]  # (the r key sorts before the w key)
    checkmate, blade = items["w73036"], items["rlt-worn-great-blade"]
    assert checkmate["stats"]["WIS"] == 5 and checkmate["stats"]["MANA"] == 5  # the site's numbers, not the wiki's 8 and 10
    assert checkmate["origin"]["overrides_wiki"] is True and blade["origin"]["overrides_wiki"] is False and blade["wiki"] is None
    # Nektropos Castle is a zone of EQL (the client flags it, zone 28, since the zone names of 2026-11-09), so both are live, and both say where they were read from
    assert level_and_codes(checkmate) == ("wiki", ["live-source:Nektropos Castle", "source-eql-tools"])
    assert level_and_codes(blade) == ("wiki", ["live-source:Nektropos Castle", "source-eql-tools"])
    reason = next(r for r in blade["evidence"]["reasons"] if r["code"] == "source-eql-tools")
    assert reason["seal"] == "player" and "EQ Legends Tools" in reason["text"]
    section = summary["eqlegendstools"]
    assert section["pages"] == 2 and [o["key"] for o in section["overridden"]] == ["w73036"] and [a["key"] for a in section["added"]] == ["rlt-worn-great-blade"]
    assert {"stats.WIS", "stats.MANA"} <= {d["field"] for d in section["disagreements"]}  # (the invented wiki page also lacks the site's other stats)
    assert read_json(out / "catalog-summary.json")["eqlegendstools"] == section


def test_the_attribution_of_the_catalog_is_the_wiki_s_and_unchanged(tmp_path, quests_file):  # noqa: F811
    _, out = build(tmp_path, [WIKI_CHECKMATE], quests_file, eqlegendstools_dir=snapshot(tmp_path))
    assert read_json(out / "catalog.json")["attribution"] == ATTRIBUTION
    assert ATTRIBUTION.startswith("Item data adapted from eqlwiki.com (CC BY-SA 4.0) by the eqlwiki contributors;")


def test_the_provenance_names_the_zone_page_and_the_manifest_lists_the_items_read_from_the_site(tmp_path, quests_file):  # noqa: F811
    folder = snapshot(tmp_path)
    _, out = build(tmp_path, [WIKI_CHECKMATE], quests_file, eqlegendstools_dir=folder)
    inputs = {record["file"]: record for record in read_json(out / "catalog.json")["provenance"]["inputs"]}
    record = inputs["https://eqlegendstools.com/zones/nektropos-castle/"]
    assert record["sha256"] == json.loads((folder / "manifest.json").read_text(encoding="ascii"))["sha256"] and record["date"] == "2026-10-25"
    manifest = read_json(out / "sources-manifest.json")
    assert manifest["items"] == {"w73036": {"title": "Checkmate", "revid": 730360}}  # (the wiki items only: the site's own item has no wiki page or revision)
    assert manifest["eqlegendstools"] == {
        "rlt-worn-great-blade": {"title": "Worn Great Blade", "slug": "worn-great-blade"},
        "w73036": {"title": "Checkmate", "slug": "checkmate"},
    }


def test_without_the_option_the_catalog_is_the_wikis_alone(tmp_path, quests_file):  # noqa: F811
    summary, out = build(tmp_path, [WIKI_CHECKMATE], quests_file)
    assert "eqlegendstools" not in summary and "eqlegendstools" not in read_json(out / "sources-manifest.json")
    item = items_by_key(out)["w73036"]
    assert "origin" not in item and item["stats"]["WIS"] == 8
    assert all("eqlegendstools" not in record["file"] for record in read_json(out / "catalog.json")["provenance"]["inputs"])


def test_a_fetch_that_is_not_finished_stops_the_build(tmp_path, quests_file):  # noqa: F811
    folder = snapshot(tmp_path)
    (folder / "manifest.json").unlink()
    with pytest.raises(BuildError, match="EQ Legends Tools fetch .*manifest.json"):
        build(tmp_path, [WIKI_CHECKMATE], quests_file, eqlegendstools_dir=folder)


def test_the_command_takes_the_option(tmp_path, quests_file, capsys, monkeypatch):  # noqa: F811
    from test_catalog import CLIENT, RULES, make_wiki

    wiki = make_wiki(tmp_path / "wiki", [WIKI_CHECKMATE])
    folder = snapshot(tmp_path)
    monkeypatch.setattr("trioforge.data.catalog.REPO_ROOT", REPO)
    code = main(["--wiki", str(wiki), "--client", str(CLIENT), "--eqlegendstools", str(folder), "--out", str(tmp_path / "out"), "--quests", str(quests_file),
                 "--rules", str(RULES), "--date", DATE, "--workers", "0"])  # fmt: skip
    assert code == 0 and "catalog: 2 items" in capsys.readouterr().out
    assert "rlt-worn-great-blade" in items_by_key(tmp_path / "out")


def test_a_missing_directory_is_a_build_error_that_names_it(tmp_path, quests_file):  # noqa: F811
    missing = tmp_path / "no-such-fetch"
    with pytest.raises(BuildError, match="no-such-fetch"):
        build(tmp_path, [WIKI_CHECKMATE], quests_file, eqlegendstools_dir=missing)


def test_a_damaged_manifest_is_a_build_error_that_names_the_directory(tmp_path, quests_file):  # noqa: F811
    folder = snapshot(tmp_path)
    (folder / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(BuildError, match="2026-10-25"):
        build(tmp_path, [WIKI_CHECKMATE], quests_file, eqlegendstools_dir=folder)


def test_a_page_the_reader_cannot_open_is_a_build_error_that_names_the_directory(tmp_path, quests_file, monkeypatch):  # noqa: F811
    folder = snapshot(tmp_path)

    def broken(directory):
        raise FileNotFoundError("raw/item-x.html")

    monkeypatch.setattr("trioforge.data.catalog.read_eqlt_snapshot", broken)
    with pytest.raises(BuildError, match="2026-10-25"):
        build(tmp_path, [WIKI_CHECKMATE], quests_file, eqlegendstools_dir=folder)


def test_a_new_item_with_no_class_line_is_left_out_and_the_build_says_so(tmp_path, quests_file, capsys, monkeypatch):  # noqa: F811
    from test_catalog import CLIENT, RULES, make_wiki

    classless = PAGES["worn-great-blade"].replace("<li>Class: WAR PAL SHD BER</li>", "")
    assert classless != PAGES["worn-great-blade"]
    monkeypatch.setitem(PAGES, "worn-great-blade", classless)
    folder = snapshot(tmp_path)
    summary, out = build(tmp_path, [WIKI_CHECKMATE], quests_file, eqlegendstools_dir=folder)
    assert sorted(items_by_key(out)) == ["w73036"]  # not added with the parser's default of all classes
    assert summary["eqlegendstools"]["skipped"] == [{"slug": "worn-great-blade", "name": "Worn Great Blade", "missing": ["class"]}]
    assert summary["warnings"]["build"]["eqlegendstools-skipped"] == 1
    wiki = make_wiki(tmp_path / "wiki-cli", [WIKI_CHECKMATE])
    monkeypatch.setattr("trioforge.data.catalog.REPO_ROOT", REPO)
    code = main(["--wiki", str(wiki), "--client", str(CLIENT), "--eqlegendstools", str(folder), "--out", str(tmp_path / "out-cli"), "--quests", str(quests_file),
                 "--rules", str(RULES), "--date", DATE, "--workers", "0"])  # fmt: skip
    shown = capsys.readouterr()
    assert code == 0 and "worn-great-blade" in shown.err and "class" in shown.err


def test_a_name_on_two_wiki_pages_stops_the_build_and_names_the_item(tmp_path, quests_file):  # noqa: F811
    twin = synthetic_record(
        73037, "Checkmate", statsblock="Slot: EAR<br>\nSize: TINY WT: 0.1<br>\nClass: WAR", dropsfrom="\n[[Nektropos Castle]]\n* [[The Game Master]]\n"
    )
    with pytest.raises(BuildError, match=r"EQ Legends Tools items.*checkmate.*w73036.*w73037"):
        build(tmp_path, [WIKI_CHECKMATE, twin], quests_file, eqlegendstools_dir=snapshot(tmp_path))


@pytest.mark.skipif(not (REPO / "derived" / "catalog.json").is_file(), reason="derived/catalog.json is not built")
def test_the_committed_catalog_keeps_the_tools_items_and_none_of_its_reasons_says_the_client_does_not_flag_their_zone():
    """The client flags Nektropos Castle since the zone names of 2026-11-09 and the hand list no longer says the zone is unflagged: the 46 items of the zone page are live by the client's flag, at the wiki level,
    and no public reason of any item says that the client does not flag that zone."""
    items = read_json(REPO / "derived" / "catalog.json")["items"]
    tools = [item for item in items if (item.get("origin") or {}).get("source") == "eqlegendstools"]
    assert len(tools) == 46
    assert not [item["key"] for item in items if item["evidence"]["level"] == "strict"]
    for item in items:
        for reason in item["evidence"]["reasons"]:
            assert not ("Nektropos Castle" in reason["text"] and "does not flag" in reason["text"]), item["key"]
    for item in tools:
        live = [reason for reason in item["evidence"]["reasons"] if reason["code"] == "live-source:Nektropos Castle"]
        assert item["evidence"]["level"] == "wiki" and [reason["seal"] for reason in live] == ["client"], item["key"]
        assert "source-eql-tools" in [reason["code"] for reason in item["evidence"]["reasons"]], item["key"]
