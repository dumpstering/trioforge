"""Tests for the catalog build's side of the second parser review (2026-10-14).

The build gives a bullet that names a known zone the place of a zone line (with its own alias table), grades foraged
zones and quests found by their target, and on the whole cached pull the junk the first reader made zones of is gone.
Pages are synthetic (invented names) or the cached pull itself (skipped where the git-ignored cache is absent).
"""

import copy
import gzip
import json
import re
import shutil
from pathlib import Path

import pytest

from trioforge.data.catalog import build_catalog, validate_catalog

REPO = Path(__file__).resolve().parents[2]
CLIENT = REPO / "derived" / "client"
RULES = REPO / "rules"
DATE = "2026-10-14"


def synthetic_record(pageid, title, *, statsblock="Slot: EAR<br>\nAC: 5", era="Classic Era", **params):
    body = "".join(f"|{name} = {value}\n" for name, value in params.items())
    content = "{{" + era + "}}\n{{Itempage\n|itemname = " + title + "\n|statsblock =\n" + statsblock + "\n" + body + "}}"
    return {"pageid": pageid, "ns": 0, "title": title, "revid": pageid * 10, "timestamp": "2026-10-01T00:00:00Z", "content": content}


def make_wiki(root, records):
    raw = root / "raw"
    raw.mkdir(parents=True)
    members = [{"pageid": r["pageid"], "title": r["title"]} for r in records]
    (raw / "members.json").write_text(json.dumps({"category": "Category:Items", "members": members}), encoding="utf-8")
    chunks = [records[start : start + 50] for start in range(0, len(records), 50)]
    for number, chunk in enumerate(chunks):
        data = {"batch": number, "pageids": [r["pageid"] for r in chunk], "pages": chunk}
        (raw / f"batch-{number:04d}.json.gz").write_bytes(gzip.compress(json.dumps(data).encode("ascii"), mtime=0))
    manifest = {"date": DATE, "category": "Category:Items", "members": len(records), "batches": len(chunks), "pages": len(records), "missing": 0}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def quests_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("quests") / "quests.json"
    quests = [
        {"title": "Zorblax Tests", "wiki_title": None, "giver": "Zorb", "zone": "Plane of Hate", "era": "Classic Era", "rewards": [], "wants": []},
    ]
    path.write_text(json.dumps({"provenance": {"inputs": [{"file": "x", "sha256": "0" * 64, "date": "2026-10-11"}]}, "quests": quests}), encoding="utf-8")
    return path


def build(tmp_path, records, quests, *, rules=RULES):
    wiki = make_wiki(tmp_path / "wiki", records)
    out = tmp_path / "out"
    summary = build_catalog(wiki, CLIENT, out, quests_path=quests, rules_dir=rules, generated=DATE, workers=0)
    items = {item["key"]: item for item in json.loads((out / "catalog.json").read_text(encoding="utf-8"))["items"]}
    return summary, items, out


def verdict(item):
    return item["evidence"]["level"], [reason["code"] for reason in item["evidence"]["reasons"]]


# ---- the build with synthetic pages -----------------------------------------------------------------------------------------


def test_a_zone_written_as_a_bullet_is_a_zone_in_the_catalog_and_is_graded_as_one(tmp_path, quests_file):
    records = [
        synthetic_record(7001, "Zorblax Rune", dropsfrom="\n* [[Plane of Hate]]\n"),
        synthetic_record(7002, "Zorblax Crate", dropsfrom="\n* Plane of Hate\n** [[a zorblax keeper]]\n"),
        synthetic_record(7003, "Zorblax Cake", dropsfrom="\n* [[a zorblax keeper]]\n"),
    ]
    summary, items, out = build(tmp_path, records, quests_file)
    validate_catalog(json.loads((out / "catalog.json").read_text(encoding="utf-8")))
    assert items["w7001"]["sources"]["drops"] == [{"zone": "Plane of Hate", "npcs": []}]
    assert verdict(items["w7001"]) == ("wiki", ["live-source:Plane of Hate"])
    assert items["w7002"]["sources"]["drops"] == [{"zone": "Plane of Hate", "npcs": ["a zorblax keeper"]}]
    assert items["w7003"]["sources"]["drops"] == [{"zone": None, "npcs": ["a zorblax keeper"]}]  # no known zone: unchanged
    assert verdict(items["w7003"]) == ("hidden", ["no-known-source"])
    assert summary["counts"]["by_level"]["wiki"] == 2


def test_the_build_uses_the_alias_table_of_its_own_rules_folder_to_find_zone_bullets(tmp_path, quests_file):
    rules = tmp_path / "rules"
    shutil.copytree(RULES, rules)
    aliases = json.loads((rules / "zone-aliases.json").read_text(encoding="utf-8"))
    aliases["aliases"]["zorblax rune hollow"] = copy.deepcopy(aliases["aliases"]["plane of hate"])
    (rules / "zone-aliases.json").write_text(json.dumps(aliases), encoding="utf-8")
    records = [synthetic_record(7001, "Zorblax Rune", dropsfrom="\n* [[Zorblax Rune Hollow]]\n")]
    _, items, _ = build(tmp_path / "scratch", records, quests_file, rules=rules)
    assert items["w7001"]["sources"]["drops"] == [{"zone": "Zorblax Rune Hollow", "npcs": []}]
    assert verdict(items["w7001"]) == ("wiki", ["live-source:Zorblax Rune Hollow"])
    _, items, _ = build(tmp_path / "default", records, quests_file)  # the committed table does not know the zone
    assert items["w7001"]["sources"]["drops"] == [{"zone": None, "npcs": ["Zorblax Rune Hollow"]}]


def test_foraged_zones_and_quest_targets_are_graded_in_the_build(tmp_path, quests_file):
    records = [
        synthetic_record(7001, "Zorblax Root", foraged="\n* [[Plane of Hate]]\n* [[Nowhere Land]]\n"),
        synthetic_record(7002, "Zorblax Moss", foraged="\n* [[Nowhere Land]]\n"),
        synthetic_record(7003, "Zorblax Cape", relatedquests="\n* [[Zorblax Tests|Zorblax Test of Courage]]\n"),
    ]
    summary, items, out = build(tmp_path, records, quests_file)
    validate_catalog(json.loads((out / "catalog.json").read_text(encoding="utf-8")))
    assert items["w7001"]["sources"]["foraged"] == [{"zone": "Plane of Hate"}, {"zone": "Nowhere Land"}]
    assert verdict(items["w7001"]) == ("wiki", ["live-source:foraged"])
    assert verdict(items["w7002"]) == ("hidden", ["zones-unmapped"])
    assert items["w7003"]["sources"]["quests"] == ["Zorblax Tests"]
    assert items["w7003"]["sources"]["quest_labels"] == [{"title": "Zorblax Tests", "label": "Zorblax Test of Courage"}]
    assert verdict(items["w7003"]) == ("wiki", ["live-source:quest"])
    assert summary["unmapped_zones"] == [{"zone": "Nowhere Land", "items": 2}]


# ---- the whole cached pull (skipped where the git-ignored cache is absent) ----------------------------------------------------

CACHES = sorted((REPO / "sources" / "eqlwiki").glob("*/manifest.json"))
CACHE_READY = bool(CACHES) and (REPO / "derived" / "quests.json").is_file()


@pytest.fixture(scope="module")
def real_build(tmp_path_factory):
    out = tmp_path_factory.mktemp("real-build")
    summary = build_catalog(CACHES[-1].parent, CLIENT, out, quests_path=REPO / "derived" / "quests.json", generated=DATE, workers=4)
    items = {item["key"]: item for item in json.loads((out / "catalog.json").read_text(encoding="utf-8"))["items"]}
    return summary, items


@pytest.mark.skipif(not CACHE_READY, reason="needs the cached wiki pull (sources/eqlwiki/<date>, git-ignored) and derived/quests.json")
def test_the_fifteen_wind_runes_are_all_drops_of_the_plane_of_sky(real_build):
    _, items = real_build
    runes = [item for item in items.values() if item["name"].startswith("Wind Rune ")]
    assert len(runes) == 15
    for rune in runes:
        assert rune["sources"]["drops"] == [{"zone": "Plane of Sky", "npcs": []}], rune["name"]
        assert rune["evidence"]["level"] == "wiki" and "live-source:Plane of Sky" in verdict(rune)[1], rune["name"]


@pytest.mark.skipif(not CACHE_READY, reason="needs the cached wiki pull (sources/eqlwiki/<date>, git-ignored) and derived/quests.json")
def test_the_known_pages_of_the_review_are_graded_as_the_review_expects(real_build):
    _, items = real_build
    by_title = {item["wiki"]["title"]: item for item in items.values()}
    assert verdict(by_title["Griffin-Hide Armguards"]) == ("wiki", ["live-source:quest"])
    assert by_title["Essence of Earth"]["charges"] == 2
    assert len(by_title["Fine Steel Naginata"]["categories"]) == 4
    for title in ("Chilled Tundra Root", "Morning Dew", "Fishing Grubs"):
        level, codes = verdict(by_title[title])
        assert level == "wiki" and "live-source:foraged" in codes, title


@pytest.mark.skipif(not CACHE_READY, reason="needs the cached wiki pull (sources/eqlwiki/<date>, git-ignored) and derived/quests.json")
def test_no_zone_of_the_whole_pull_is_a_map_position_or_a_line_of_prose(real_build):
    summary, items = real_build
    zones = set()
    for item in items.values():
        zones.update(drop["zone"] for drop in item["sources"]["drops"] if drop["zone"])
        zones.update(sold["zone"] for sold in item["sources"]["sold_by"] if sold["zone"])
        zones.update(forage["zone"] for forage in item["sources"].get("foraged", []))
    assert len(zones) > 150
    for zone in zones:  # the first reader made zones of "-522.1356", "8AM EST" and whole sentences
        assert len(zone.split()) <= 8 and not re.search(r"[0-9.;:!?\"+_]", zone), zone
    unmapped = {entry["zone"] for entry in summary["unmapped_zones"]}
    assert summary["unmapped_zone_total"] < 60, summary["unmapped_zone_total"]  # it was 195
    assert not any(name.startswith("-") or name[:1].isdigit() for name in unmapped), sorted(unmapped)[:20]


@pytest.mark.skipif(not CACHE_READY, reason="needs the cached wiki pull (sources/eqlwiki/<date>, git-ignored) and derived/quests.json")
def test_foraged_zones_are_in_the_catalog_for_every_item_whose_page_lists_some(real_build):
    _, items = real_build
    foraged = [item for item in items.values() if item["sources"].get("foraged")]
    assert 100 <= len(foraged) <= 140
    for item in foraged:
        assert all(entry["zone"] for entry in item["sources"]["foraged"])


@pytest.mark.skipif(not CACHE_READY, reason="needs the cached wiki pull (sources/eqlwiki/<date>, git-ignored) and derived/quests.json")
def test_the_class_tests_of_the_plane_of_sky_are_wiki_through_their_zone_link_and_a_bare_zone_link_is_none(real_build):
    _, items = real_build
    by_title = {item["wiki"]["title"]: item for item in items.values()}
    for title in ("Aldryn, Blade of the Ocean", "Wu's Fist of Mastery", "Back Straps of Mastery"):
        assert verdict(by_title[title]) == ("wiki", ["live-source:quest"]), title  # [[Plane of Sky|Paladin Test of Sacrifice]] and the like
    # "The Sword of Nobility" is in the quest table, but its page is out of era; the link to a zone beside it has no label
    for key in ("w53446", "w54305"):  # A Pendant, Note to Kanthuk
        level, codes = verdict(items[key])
        assert level == "hidden" and "live-source:quest" not in codes, key
    linked = [
        item
        for item in items.values()
        if any(r["code"] == "live-source:quest" and r["text"].startswith("The item page links it to a quest in") for r in item["evidence"]["reasons"])
    ]
    assert len(linked) == 99  # the class tests of the Plane of Sky, none of them with another live source
    assert all(item["evidence"]["level"] == "wiki" and item["sources"]["quest_labels"] for item in linked)
