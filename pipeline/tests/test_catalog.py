"""Tests for the catalog builder: reading the wiki cache and the client extract, grading, writing, refusing.

Wiki pages are the recorded fixtures (real eqlwiki text, see fixtures/wiki/README.md) or synthetic pages with
invented names; a test that flags an item (a seen flag, a community report, a listed catalog key) builds only
synthetic ones. The client extract, the rules and the zone aliases are the committed ones; the quest table is
a small synthetic one.
"""

import ast
import copy
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from trioforge.data import catalog
from trioforge.data.catalog import (
    ATTRIBUTION,
    OUTPUT_FILES,
    BuildError,
    build_catalog,
    check_client,
    check_seen_output,
    load_community_keys,
    load_seen_keys,
    main,
    read_wiki,
    validate_catalog,
)
from trioforge.privacy.scan import scan_bytes
from trioforge.sources.eqlwiki import fixture_slug, page_records

REPO = Path(__file__).resolve().parents[2]
CLIENT = REPO / "derived" / "client"
RULES = REPO / "rules"
FIXTURES = REPO / "fixtures" / "wiki"
DATE = "2026-10-14"


def fixture_record(title):
    path = FIXTURES / f"{fixture_slug(title)}.json"
    (record,) = page_records(json.loads(path.read_text(encoding="utf-8")))
    return record


def synthetic_record(pageid, title, *, statsblock="Slot: EAR<br>\nAC: 5", era="Classic Era", **params):
    body = "".join(f"|{name} = {value}\n" for name, value in params.items())
    head = "{{" + era + "}}\n" if era else ""
    content = head + "{{Itempage\n|itemname = " + title + "\n|statsblock =\n" + statsblock + "\n" + body + "}}"
    return {
        "pageid": pageid,
        "ns": 0,
        "title": title,
        "revid": pageid * 10,
        "timestamp": "2026-10-01T00:00:00Z",
        "content": content,
    }


def plain_record(pageid, title, content, ns=0):
    return {"pageid": pageid, "ns": ns, "title": title, "revid": pageid * 10, "timestamp": "2026-10-01T00:00:00Z", "content": content}


def missing_record(pageid):
    return {"pageid": pageid, "ns": None, "title": None, "revid": None, "timestamp": None, "content": None, "missing": True}


def make_wiki(root, records, *, date=DATE, category="Category:Items"):
    """A finished fetch of these page records, written the way the fetcher writes it."""
    raw = root / "raw"
    raw.mkdir(parents=True)
    members = [{"pageid": r["pageid"], "title": r["title"] or "Gone Page"} for r in records]
    (raw / "members.json").write_text(json.dumps({"category": category, "members": members}), encoding="utf-8")
    chunks = [records[start : start + 50] for start in range(0, len(records), 50)]
    for number, chunk in enumerate(chunks):
        data = {"batch": number, "pageids": [r["pageid"] for r in chunk], "pages": chunk}
        (raw / f"batch-{number:04d}.json.gz").write_bytes(gzip.compress(json.dumps(data).encode("ascii"), mtime=0))
    manifest = {
        "date": date,
        "category": category,
        "members": len(records),
        "batches": len(chunks),
        "pages": sum(1 for r in records if not r.get("missing")),
        "missing": sum(1 for r in records if r.get("missing")),
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def quests_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("quests") / "quests.json"
    quests = [
        {
            "title": "Paladin Test of Spirit",
            "wiki_title": None,
            "giver": "Zorb",
            "zone": "Plane of Sky",
            "era": "Sky Era",
            "rewards": ["Girdle of Faith"],
            "wants": ["Zorblax Token"],
        },
        {
            "title": "Far Quest",
            "wiki_title": None,
            "giver": "Zorb",
            "zone": "Kael Drakkel",
            "era": "Classic Era",
            "rewards": [],
            "wants": [],
        },
    ]
    path.write_text(json.dumps({"provenance": {"inputs": [{"file": "x", "sha256": "0" * 64, "date": "2026-10-11"}]}, "quests": quests}), encoding="utf-8")
    return path


def rules_without_reports(tmp_path):
    """The hand-written rules of the checkout and no list of reports. A catalog built from a fixture is built from these, whatever reports the checkout has accepted: the first one
    would otherwise be an input of every such build (its file in the provenance, its key among the unknown ones), and these tests are about the fixture."""
    folder = tmp_path / "rules-without-reports"
    folder.mkdir(exist_ok=True)
    for name in ("hand-lists.json", "zone-aliases.json"):
        shutil.copy(RULES / name, folder / name)
    return folder


def build(tmp_path, records, quests, *, out=None, client=CLIENT, rules=None, **kwargs):
    wiki = make_wiki(tmp_path / "wiki", records)
    out = out or tmp_path / "out"
    rules = rules_without_reports(tmp_path) if rules is None else rules
    kwargs.setdefault("workers", 0)
    summary = build_catalog(wiki, client, out, quests_path=quests, rules_dir=rules, generated=DATE, **kwargs)
    return summary, out


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def items_by_key(out):
    return {item["key"]: item for item in read_json(out / "catalog.json")["items"]}


def level_and_codes(item):
    return item["evidence"]["level"], [reason["code"] for reason in item["evidence"]["reasons"]]


# ---- the output -----------------------------------------------------------------------------------------


def test_two_fixture_pages_build_a_sorted_valid_catalog(tmp_path, quests_file):
    summary, out = build(tmp_path, [fixture_record("Engineer's Ring"), fixture_record("Girdle of Faith")], quests_file)
    document = read_json(out / "catalog.json")
    assert [item["key"] for item in document["items"]] == ["w16279", "w42638"]  # string order
    assert document["license"] == "CC BY-SA 4.0" and document["attribution"] == ATTRIBUTION
    assert document["version"] == DATE
    validate_catalog(document)
    items = {item["key"]: item for item in document["items"]}
    assert level_and_codes(items["w42638"]) == ("wiki", ["live-source:Plane of Hate"])
    assert level_and_codes(items["w16279"]) == ("wiki", ["live-source:quest"])  # the class-test quest's giver is in Plane of Sky
    assert summary["counts"]["items"] == 2


def test_the_four_files_are_written_and_nothing_else(tmp_path, quests_file):
    _, out = build(tmp_path, [fixture_record("Engineer's Ring")], quests_file)
    assert sorted(path.name for path in out.iterdir()) == sorted(OUTPUT_FILES)


def test_the_catalog_file_has_one_item_per_line_in_utf_8_with_unix_line_ends(tmp_path, quests_file):
    _, out = build(tmp_path, [fixture_record("Engineer's Ring"), fixture_record("Girdle of Faith")], quests_file)
    data = (out / "catalog.json").read_bytes()
    text = data.decode("utf-8")
    assert text.startswith('{\n "version": "2026-10-14",\n "license": "CC BY-SA 4.0",\n "attribution": ') and text.endswith("}\n")
    assert b"\r" not in data
    assert sum(1 for line in text.split("\n") if line.startswith('  {"key":"w')) == 2


def test_the_provenance_names_every_input_with_its_hash_and_date(tmp_path, quests_file):
    _, out = build(tmp_path, [fixture_record("Engineer's Ring")], quests_file)
    provenance = read_json(out / "catalog.json")["provenance"]
    assert provenance["generated"] == DATE and provenance["generator"].startswith("trioforge.data.catalog ")
    by_file = {record["file"]: record for record in provenance["inputs"]}
    assert list(by_file) == sorted(by_file)
    assert set(by_file) == {
        "https://eqlwiki.com/index.php?title=Category:Items",
        "derived/client/zones.json",
        "derived/quests.json",
        "rules/hand-lists.json",
        "rules/zone-aliases.json",
    }
    assert by_file["derived/client/zones.json"]["sha256"] == hashlib.sha256((CLIENT / "zones.json").read_bytes()).hexdigest()
    assert by_file["derived/client/zones.json"]["date"] == "2026-09-22"  # the date of ZoneNames.txt, the patch
    assert by_file["rules/hand-lists.json"]["sha256"] == hashlib.sha256((RULES / "hand-lists.json").read_bytes()).hexdigest()
    assert by_file["derived/quests.json"]["date"] == "2026-10-11"
    assert by_file["https://eqlwiki.com/index.php?title=Category:Items"]["date"] == DATE
    for record in provenance["inputs"]:
        assert len(record["sha256"]) == 64
    for name in ("catalog-summary.json", "catalog-warnings.json", "sources-manifest.json"):
        assert read_json(out / name)["provenance"] == provenance


def test_the_sources_manifest_maps_each_key_to_its_page_title_and_revision(tmp_path, quests_file):
    _, out = build(tmp_path, [fixture_record("Engineer's Ring"), fixture_record("Girdle of Faith")], quests_file)
    document = read_json(out / "sources-manifest.json")
    assert document["license"] == "CC BY-SA 4.0"
    assert document["items"] == {
        "w16279": {"title": "Girdle of Faith", "revid": 180733},
        "w42638": {"title": "Engineer's Ring", "revid": 193407},
    }


def test_the_summary_counts_by_level_slot_class_and_reason(tmp_path, quests_file):
    records = [
        fixture_record("Engineer's Ring"),  # wiki, FINGER, nine classes
        fixture_record("Mask of Deception"),  # hidden: removed by a patch, FACE, BRD ROG
        synthetic_record(9001, "Zorblax Hat", statsblock="Slot: HEAD\nClass: WAR", dropsfrom="[[Kael Drakkel]]"),  # hidden, zones-not-in-eql
        plain_record(9002, "Zorblax Note", "just a note"),  # not an item
    ]
    summary, _ = build(tmp_path, records, quests_file)
    counts = summary["counts"]
    assert counts["items"] == 3 and counts["skipped"] == {"no-itempage-template": 1}
    assert counts["by_level"] == {"strict": 0, "wiki": 1, "disputed": 0, "hidden": 2}
    assert counts["wearables"] == 3 and counts["wearables_by_level"] == {"strict": 0, "wiki": 1, "disputed": 0, "hidden": 2}
    assert counts["by_slot"]["FINGER"] == {"strict": 0, "wiki": 1, "disputed": 0, "hidden": 0}
    assert counts["by_slot"]["HEAD"]["hidden"] == 1 and counts["by_slot"]["FACE"]["hidden"] == 1
    assert counts["by_class"]["WAR"] == {"strict": 0, "wiki": 1, "disputed": 0, "hidden": 1}
    assert counts["by_class"]["BRD"]["hidden"] == 1 and counts["by_class"]["CLR"]["wiki"] == 1 and counts["by_class"]["BST"]["wiki"] == 0
    assert counts["by_reason"] == {"live-source": 1, "removed-by-patch": 1, "zones-not-in-eql": 1}
    assert counts["hidden_by_reason"] == {"removed-by-patch": 1, "zones-not-in-eql": 1}
    assert list(counts["by_slot"]) == (
        "HEAD FACE EAR NECK SHOULDERS ARMS BACK WRIST HANDS FINGER CHEST LEGS FEET WAIST RANGE AMMO PRIMARY SECONDARY "
        "CHARM POWERSOURCE"
    ).split()
    assert list(counts["by_class"]) == "WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER".split()


def test_a_class_list_of_all_counts_for_every_class(tmp_path, quests_file):
    records = [synthetic_record(9001, "Zorblax Ring", statsblock="Slot: FINGER", dropsfrom="[[Plane of Hate]]")]
    summary, _ = build(tmp_path, records, quests_file)
    for code, found in summary["counts"]["by_class"].items():
        assert found["wiki"] == 1, code


def test_pages_that_are_not_items_are_skipped_with_their_reason_and_never_become_items(tmp_path, quests_file):
    records = [
        fixture_record("Engineer's Ring"),
        plain_record(9101, "Old Name", "#REDIRECT [[Zorblax Ring]]"),
        plain_record(9102, "A Disambiguation", "Zorblax may mean:\n* [[Zorblax Ring]]"),
        missing_record(9103),
        plain_record(9104, "Talk:Zorblax Ring", "{{Itempage|statsblock=Slot: EAR}}", ns=1),
        plain_record(9105, "Empty Stats", "{{Itempage|itemname=Empty Stats}}"),
        plain_record(9106, "Blank Page", "   "),
    ]
    summary, out = build(tmp_path, records, quests_file)
    assert summary["counts"]["skipped"] == {
        "empty": 1,
        "empty-statsblock": 1,
        "missing": 1,
        "namespace": 1,
        "no-itempage-template": 1,
        "redirect": 1,
    }
    assert summary["counts"]["items"] == 1 and list(items_by_key(out)) == ["w42638"]
    skipped = read_json(out / "catalog-warnings.json")["skipped"]
    assert {(s["pageid"], s["reason"]) for s in skipped} == {
        (9101, "redirect"),
        (9102, "no-itempage-template"),
        (9103, "missing"),
        (9104, "namespace"),
        (9105, "empty-statsblock"),
        (9106, "empty"),
    }
    assert {s["pageid"]: s["title"] for s in skipped}[9103] is None


def test_parse_warnings_are_counted_by_code_and_listed_with_key_code_and_field(tmp_path, quests_file):
    records = [synthetic_record(9201, "Zorblax Ring", statsblock="Slot: EAR<br>\nGibberish: line", dropsfrom="[[Plane of Hate]]")]
    summary, out = build(tmp_path, records, quests_file)
    assert read_json(out / "catalog-warnings.json")["warnings"] == [{"key": "w9201", "code": "unparsed-line", "field": "statsblock"}]
    assert summary["warnings"]["parse_by_code"] == {"unparsed-line": 1}
    assert summary["warnings"]["items_with_parse_warnings"] == 1


def test_zone_names_the_alias_table_does_not_know_are_reported_most_common_first(tmp_path, quests_file):
    records = [
        fixture_record("Rusty Dagger"),  # "Various Zones", and a vendor in East Freeport
        synthetic_record(9301, "Zorblax Ring", dropsfrom="[[Blarg Marsh]]\n[[Plane of Hate]]"),
        synthetic_record(9302, "Quuxen Ring", dropsfrom="[[Blarg Marsh]]\n[[Blarg Marsh]]\n[[Zorblax Keep]]"),
    ]
    summary, out = build(tmp_path, records, quests_file)
    assert summary["unmapped_zones"] == [
        {"zone": "Blarg Marsh", "items": 2},  # once per item, however many times a page repeats it
        {"zone": "Various Zones", "items": 1},
        {"zone": "Zorblax Keep", "items": 1},
    ]
    assert summary["unmapped_zone_total"] == 3
    items = items_by_key(out)
    assert level_and_codes(items["w9302"]) == ("hidden", ["zones-unmapped"])
    assert level_and_codes(items["w9301"])[0] == "wiki"  # one live zone is enough
    assert level_and_codes(items["w17039"])[0] == "wiki"  # the vendor in East Freeport


def test_unknown_era_names_are_ignored_and_counted(tmp_path, quests_file):
    records = [
        synthetic_record(9401, "Zorblax Ring", era="Zorblaxian Era", dropsfrom="[[Plane of Hate]]"),
        synthetic_record(9402, "Quuxen Ring", era="Zorblaxian Era", dropsfrom="[[Plane of Hate]]"),
    ]
    summary, out = build(tmp_path, records, quests_file)
    assert summary["unknown_era_tags"] == {"Zorblaxian Era": 2}
    assert {level_and_codes(item)[0] for item in items_by_key(out).values()} == {"wiki"}


def test_names_that_differ_only_by_look_alike_letters_or_case_are_reported_as_confusable(tmp_path, quests_file):
    records = [
        fixture_record("Rusty Dagger"),
        synthetic_record(9501, "Rusty Dаgger"),  # a Cyrillic a
        synthetic_record(9502, "rusty dagger"),
        synthetic_record(9503, "Bone Chips"),
        synthetic_record(9504, "Bone Chips"),  # the same name twice is a duplicate, not a look-alike
    ]
    summary, _ = build(tmp_path, records, quests_file)
    confusable = summary["confusable_names"]
    assert confusable["warning"] == "confusable-names"
    assert confusable["pairs"] == 3 and sorted(confusable["examples"]) == [["w17039", "w9501"], ["w17039", "w9502"], ["w9501", "w9502"]]
    assert summary["warnings"]["build"]["confusable-names"] == 3


# ---- evidence in the catalog ----------------------------------------------------------------------------


def test_real_hand_lists_hide_a_removed_item_and_a_cultural_recipe(tmp_path, quests_file):
    records = [fixture_record("Mask of Deception"), fixture_record("Ogre Bouncer Shield"), fixture_record("Banded Belt")]
    _, out = build(tmp_path, records, quests_file)
    items = items_by_key(out)
    assert level_and_codes(items["w301"]) == ("hidden", ["removed-by-patch"])
    assert level_and_codes(items["w49376"]) == ("hidden", ["cultural-container"])
    assert level_and_codes(items["w32365"]) == ("wiki", ["live-source:craft"])


def test_an_ingredient_that_is_itself_out_of_era_makes_a_recipe_unusable(tmp_path, quests_file):
    records = [
        synthetic_record(9601, "Zorblax Helm", statsblock="Slot: HEAD", playercrafted="* [[Blacksmithing]]\n** In [[Forge]]:\n:: 1 x [[Velium Bar]]"),
        synthetic_record(9602, "Velium Bar", statsblock="WT: 1.0  Size: SMALL", era="Velious Era"),
        synthetic_record(9603, "Zorblax Greaves", statsblock="Slot: LEGS", playercrafted="* [[Blacksmithing]]\n** In [[Forge]]:\n:: 1 x [[Iron Bar]]"),
        synthetic_record(9604, "Iron Bar", statsblock="WT: 1.0  Size: SMALL"),
    ]
    _, out = build(tmp_path, records, quests_file)
    items = items_by_key(out)
    assert level_and_codes(items["w9601"]) == ("hidden", ["out-of-era-ingredient"])
    assert level_and_codes(items["w9603"]) == ("wiki", ["live-source:craft"])


def test_a_name_that_two_pages_share_finds_no_quest_by_reward_or_hand_in(tmp_path, quests_file):
    records = [
        synthetic_record(9701, "Zorblax Token", statsblock="Slot: EAR", dropsfrom="[[Plane of Hate]]"),
        synthetic_record(9702, "Quuxen Token", statsblock="Slot: EAR", dropsfrom="[[Plane of Hate]]"),
        synthetic_record(9703, "Quuxen Token", statsblock="Slot: NECK", dropsfrom="[[Plane of Hate]]"),
    ]
    _, out = build(tmp_path, records, quests_file)  # the quest table says a quest takes a "Zorblax Token"
    items = items_by_key(out)
    assert "not-for-bis" in level_and_codes(items["w9701"])[1]
    assert "not-for-bis" not in level_and_codes(items["w9702"])[1]


def test_a_deity_locked_item_carries_not_for_default_kits(tmp_path, quests_file):
    records = [
        synthetic_record(9801, "Zorblax Ring", statsblock="Slot: FINGER\nDeity: Tunare", dropsfrom="[[Plane of Hate]]"),
        synthetic_record(9802, "Quuxen Ring", statsblock="Slot: FINGER", dropsfrom="[[Plane of Hate]]"),
        synthetic_record(9803, "Blarg Ring", statsblock="Slot: FINGER\nMAGIC ITEM  TEMPORARY", dropsfrom="[[Plane of Hate]]"),
    ]
    _, out = build(tmp_path, records, quests_file)
    items = items_by_key(out)
    assert level_and_codes(items["w9801"]) == ("wiki", ["live-source:Plane of Hate", "not-for-default-kits"])
    assert level_and_codes(items["w9802"]) == ("wiki", ["live-source:Plane of Hate"])
    assert level_and_codes(items["w9803"]) == ("wiki", ["live-source:Plane of Hate", "not-for-bis"])
    assert items["w9801"]["deity"] == ["Tunare"]


def test_a_wiki_banner_hides_an_item_and_counts_as_a_hidden_reason_while_revamped_is_only_a_note(tmp_path, quests_file):
    deleted = "{{delete}} replaced in EQL\n" + synthetic_record(9701, "Zorblax Ring", statsblock="Slot: FINGER", dropsfrom="[[Plane of Hate]]")["content"]
    revamped = "{{revamped}}\n" + synthetic_record(9702, "Quuxen Ring", statsblock="Slot: FINGER")["content"]  # no source at all
    removed = synthetic_record(9704, "Blarg Ring", statsblock="Slot: FINGER", dropsfrom="ITEM REMOVED FROM GAME")
    records = [
        plain_record(9701, "Zorblax Ring", deleted),
        plain_record(9702, "Quuxen Ring", revamped),
        synthetic_record(9703, "Plain Ring", statsblock="Slot: FINGER", dropsfrom="[[Plane of Hate]]"),
        removed,
    ]
    summary, out = build(tmp_path, records, quests_file)
    items = items_by_key(out)
    assert level_and_codes(items["w9701"]) == ("hidden", ["wiki-marked-not-in-eql"])
    assert level_and_codes(items["w9702"]) == ("hidden", ["no-known-source", "wiki-marked-revamped"])
    assert level_and_codes(items["w9703"]) == ("wiki", ["live-source:Plane of Hate"])
    assert level_and_codes(items["w9704"]) == ("hidden", ["wiki-marked-removed"])
    counts = summary["counts"]
    assert counts["hidden_by_reason"] == {"no-known-source": 1, "wiki-marked-not-in-eql": 1, "wiki-marked-removed": 1}  # the note is not a reason
    assert counts["by_reason"]["wiki-marked-revamped"] == 1
    assert items["w9701"]["flags"] == ["wiki_banner_delete"] and items["w9704"]["flags"] == ["removed_note"]


def test_an_item_for_no_class_is_marked_not_for_bis_in_the_catalog(tmp_path, quests_file):
    records = [synthetic_record(9711, "Zorblax Book", statsblock="Size: TINY  WT: 0.1\nClass: NONE\nRace: NONE", dropsfrom="[[Plane of Hate]]")]
    summary, out = build(tmp_path, records, quests_file)
    (item,) = items_by_key(out).values()
    assert item["classes"] == [] and item["races"] == []
    assert level_and_codes(item) == ("wiki", ["live-source:Plane of Hate", "not-for-bis"])
    assert summary["warnings"]["parse_by_code"] == {"no-classes": 2}


# ---- shields: item_type and where it came from -------------------------------------------------------------------

OFF_HAND = "Slot: SECONDARY<br>\nAC: 10"  # worn in the off hand only, armor class, no weapon numbers
STATED_SHIELD = "Slot: SECONDARY<br>\nType: Shield<br>\nAC: 10"


def shield_rules(tmp_path, shields=(), not_shields=()):
    """A copy of the committed rules whose shield lists hold exactly these ``(key, name)`` pairs."""
    rules = tmp_path / "rules"
    shutil.copytree(RULES, rules)

    def entries(pairs):
        return [
            {"key": key, "name": name, "note": "Invented for a test.", "seal": "model", "date": DATE,
             "source": [{"kind": "public-text", "ref": "TrioForge judgment"}]}
            for key, name in pairs
        ]  # fmt: skip

    edit_json(rules / "hand-lists.json", lambda d: d.update(shields=entries(shields), not_shields=entries(not_shields)))
    return rules


def types_of(out):
    return {key: (item["item_type"], item["item_type_source"]) for key, item in items_by_key(out).items()}


def test_a_type_the_statsblock_states_is_kept_with_its_source(tmp_path, quests_file):
    records = [synthetic_record(9801, "Zorblax Guard", statsblock=STATED_SHIELD), synthetic_record(9802, "Zorblax Ring", statsblock="Slot: FINGER")]
    _, out = build(tmp_path, records, quests_file)
    assert types_of(out) == {"w9801": ("Shield", "statsblock"), "w9802": (None, None)}


@pytest.mark.parametrize(
    "name",
    ["Zorblax Shield", "ZORBLAX SHIELD", "Zorblax Battleshield", "Zorblax Buckler", "Aegis of Zorblax", "Zorblax Bulwark", "Zorblax Targe", "Zorblaxtarge"],
)
def test_an_off_hand_armor_piece_with_a_shield_word_in_its_name_is_a_shield_by_name(tmp_path, quests_file, name):
    _, out = build(tmp_path, [synthetic_record(9803, name, statsblock=OFF_HAND)], quests_file)
    assert types_of(out) == {"w9803": ("Shield", "name")}


@pytest.mark.parametrize("slots", ["SECONDARY", "BACK SECONDARY", "SECONDARY BACK"])
def test_a_shield_word_makes_a_shield_by_name_in_the_off_hand_alone_or_with_the_back(tmp_path, quests_file, slots):
    record = synthetic_record(9814, "Zorblax Shield", statsblock=f"Slot: {slots}<br>\nAC: 10")
    _, out = build(tmp_path, [record], quests_file)
    assert types_of(out) == {"w9814": ("Shield", "name")}


@pytest.mark.parametrize(
    "statsblock",
    [
        "Slot: PRIMARY SECONDARY<br>\nAC: 10",  # fits the main hand too
        "Slot: BACK PRIMARY SECONDARY<br>\nAC: 10",
        "Slot: NECK SECONDARY<br>\nAC: 10",  # any other slot makes it a held item
        "Slot: RANGE SECONDARY<br>\nAC: 10",
        "Slot: EAR SECONDARY<br>\nAC: 10",
        "Slot: BACK NECK SECONDARY<br>\nAC: 10",
        "Slot: BACK<br>\nAC: 10",  # the back alone is not the off hand
        "Slot: PRIMARY<br>\nAC: 10",
        "Slot: SECONDARY<br>\nAC: 10<br>\nSkill: 1H Slashing  Atk Delay: 30<br>\nDMG: 5",  # a weapon
        "Slot: BACK SECONDARY<br>\nAC: 10<br>\nSkill: 1H Slashing  Atk Delay: 30<br>\nDMG: 5",
        "Slot: SECONDARY<br>\nSTR: 5",  # no armor class
        "Slot: BACK SECONDARY<br>\nSTR: 5",
        "Slot: SECONDARY<br>\nAC: 0",
        "Slot: SECONDARY<br>\nAC: -5",
        "AC: 10",  # worn nowhere
    ],
)
def test_the_name_rule_needs_the_off_hand_with_at_most_the_back_no_weapon_and_an_armor_class(tmp_path, quests_file, statsblock):
    _, out = build(tmp_path, [synthetic_record(9804, "Zorblax Shield", statsblock=statsblock)], quests_file)
    assert types_of(out) == {"w9804": (None, None)}


def test_a_name_with_no_shield_word_is_no_shield_unless_the_hand_list_says_so(tmp_path, quests_file):
    records = [synthetic_record(9805, "Zorblax Guard", statsblock=OFF_HAND), synthetic_record(9806, "Quuxen Guard", statsblock=OFF_HAND)]
    _, plain = build(tmp_path, records, quests_file)
    assert types_of(plain) == {"w9805": (None, None), "w9806": (None, None)}
    listed = tmp_path / "listed"
    listed.mkdir()
    _, out = build(listed, records, quests_file, rules=shield_rules(listed, shields=[("w9806", "Quuxen Guard")]))
    assert types_of(out) == {"w9805": (None, None), "w9806": ("Shield", "hand-list")}


def test_a_hand_listed_shield_needs_no_other_condition(tmp_path, quests_file):
    rules = shield_rules(tmp_path, shields=[("w9807", "Zorblax Guard")])  # the page lists two slots and no armor class
    _, out = build(tmp_path, [synthetic_record(9807, "Zorblax Guard", statsblock="Slot: PRIMARY SECONDARY")], quests_file, rules=rules)
    assert types_of(out) == {"w9807": ("Shield", "hand-list")}


def test_a_not_shields_entry_beats_the_name_rule(tmp_path, quests_file):
    rules = shield_rules(tmp_path, not_shields=[("w9808", "Zorblax Webshield")])
    records = [synthetic_record(9808, "Zorblax Webshield", statsblock=OFF_HAND), synthetic_record(9809, "Quuxen Webshield", statsblock=OFF_HAND)]
    _, out = build(tmp_path, records, quests_file, rules=rules)
    assert types_of(out) == {"w9808": (None, None), "w9809": ("Shield", "name")}


def test_a_not_shields_entry_also_vetoes_a_shield_that_fits_the_back(tmp_path, quests_file):
    rules = shield_rules(tmp_path, not_shields=[("w9817", "Zorblax Webshield")])
    back = "Slot: BACK SECONDARY<br>\nAC: 10"
    records = [synthetic_record(9817, "Zorblax Webshield", statsblock=back), synthetic_record(9818, "Quuxen Webshield", statsblock=back)]
    summary, out = build(tmp_path, records, quests_file, rules=rules)
    assert types_of(out) == {"w9817": (None, None), "w9818": ("Shield", "name")}
    assert summary["item_types"]["shield_vetoed"] == 1


def test_a_not_shields_entry_also_beats_a_type_the_statsblock_states(tmp_path, quests_file):
    rules = shield_rules(tmp_path, not_shields=[("w9810", "Zorblax Guard")])  # the maintainer has judged the page wrong
    _, out = build(tmp_path, [synthetic_record(9810, "Zorblax Guard", statsblock=STATED_SHIELD)], quests_file, rules=rules)
    assert types_of(out) == {"w9810": (None, None)}


def test_the_sources_are_tried_in_order_statsblock_then_name_then_hand_list(tmp_path, quests_file):
    rules = shield_rules(tmp_path, shields=[("w9811", "Zorblax Shield"), ("w9812", "Quuxen Shield"), ("w9813", "Blarg Guard")])
    records = [
        synthetic_record(9811, "Zorblax Shield", statsblock=OFF_HAND),  # the name and the hand list both say it: the name is first
        synthetic_record(9812, "Quuxen Shield", statsblock=STATED_SHIELD),  # all three say it: the statsblock is first
        synthetic_record(9813, "Blarg Guard", statsblock=OFF_HAND),  # only the hand list says it
    ]
    _, out = build(tmp_path, records, quests_file, rules=rules)
    assert types_of(out) == {"w9811": ("Shield", "name"), "w9812": ("Shield", "statsblock"), "w9813": ("Shield", "hand-list")}


def test_the_summary_counts_the_shields_by_source_the_vetoed_and_the_stale_hand_list_entries(tmp_path, quests_file, capsys):
    rules = shield_rules(
        tmp_path,
        shields=[("w9821", "Quuxen Guard"), ("w9899", "Gone Guard")],  # the second key is on no page
        not_shields=[("w9822", "Zorblax Webshield"), ("w9823", "Wrong Name")],  # the second is listed under another name
    )
    records = [
        synthetic_record(9820, "Zorblax Guard", statsblock=STATED_SHIELD),  # statsblock
        synthetic_record(9821, "Quuxen Guard", statsblock=OFF_HAND),  # hand list
        synthetic_record(9822, "Zorblax Webshield", statsblock=OFF_HAND),  # vetoed
        synthetic_record(9823, "Blarg Webshield", statsblock=OFF_HAND),  # vetoed, by key, although its name differs
        synthetic_record(9824, "Zorblax Buckler", statsblock=OFF_HAND),  # name
        synthetic_record(9825, "Quuxen Buckler", statsblock=OFF_HAND),  # name
        synthetic_record(9826, "Zorblax Ring", statsblock="Slot: FINGER"),
    ]
    summary, out = build(tmp_path, records, quests_file, rules=rules)
    expected = {"shield_by_source": {"statsblock": 1, "name": 2, "hand-list": 1}, "shield_vetoed": 2, "hand_list_stale": 2}
    assert summary["item_types"] == expected
    assert read_json(out / "catalog-summary.json")["item_types"] == expected
    wiki = make_wiki(tmp_path / "again", records)
    argv = ["--wiki", str(wiki), "--client", str(CLIENT), "--quests", str(quests_file), "--rules", str(rules), "--date", DATE, "--workers", "0"]
    assert main([*argv, "--out", str(tmp_path / "again-out")]) == 0
    printed = capsys.readouterr().out
    assert "shields (4): statsblock 1, name 2, hand-list 1" in printed and "hand lists: 2 vetoed, 2 stale" in printed


def test_a_veto_that_changes_nothing_is_not_counted(tmp_path, quests_file):
    rules = shield_rules(tmp_path, not_shields=[("w9830", "Zorblax Orb")])  # an item that the name rule never called a shield
    summary, out = build(tmp_path, [synthetic_record(9830, "Zorblax Orb", statsblock=OFF_HAND)], quests_file, rules=rules)
    assert types_of(out) == {"w9830": (None, None)} and summary["item_types"]["shield_vetoed"] == 0


def test_validate_catalog_refuses_a_type_with_no_source_and_a_source_with_no_type(tmp_path, quests_file):
    records = [synthetic_record(9831, "Zorblax Shield", statsblock=OFF_HAND), synthetic_record(9832, "Zorblax Ring", statsblock="Slot: FINGER")]
    _, out = build(tmp_path, records, quests_file)
    good = read_json(out / "catalog.json")
    validate_catalog(good)
    for edit in (
        lambda d: d["items"][0].update(item_type_source=None),  # w9831 is a shield by name
        lambda d: d["items"][1].update(item_type_source="name"),  # w9832 has no type
        lambda d: d["items"][1].update(item_type="Shield"),
    ):
        bad = copy.deepcopy(good)
        edit(bad)
        with pytest.raises(ValueError, match="item_type"):
            validate_catalog(bad)


# ---- Race: NONE, Class: NONE and a page with no Race line --------------------------------------------------------


def test_race_none_and_class_none_are_empty_lists_that_are_not_for_bis_with_their_note_and_no_race_line_is_all_races(tmp_path, quests_file):
    drops = "[[Plane of Hate]]"
    records = [
        synthetic_record(9841, "Zorblax Ring", statsblock="Slot: FINGER", dropsfrom=drops),  # no Race line
        synthetic_record(9842, "Quuxen Ring", statsblock="Slot: FINGER<br>\nRace: ALL", dropsfrom=drops),
        synthetic_record(9843, "Blarg Ring", statsblock="Slot: FINGER<br>\nRace: NONE", dropsfrom=drops),
        synthetic_record(9844, "Brell Ring", statsblock="Slot: FINGER<br>\nClass: NONE", dropsfrom=drops),
        synthetic_record(9845, "Karana Ring", statsblock="Slot: FINGER<br>\nClass: NONE<br>\nRace: NONE", dropsfrom=drops),
    ]
    summary, out = build(tmp_path, records, quests_file)
    items = items_by_key(out)
    assert [(items[key]["classes"], items[key]["races"]) for key in ("w9841", "w9842", "w9843", "w9844", "w9845")] == [
        (["ALL"], ["ALL"]),
        (["ALL"], ["ALL"]),
        (["ALL"], []),
        ([], ["ALL"]),
        ([], []),
    ]
    assert level_and_codes(items["w9841"]) == ("wiki", ["live-source:Plane of Hate"])  # a missing line is all races, in silence
    assert level_and_codes(items["w9842"]) == ("wiki", ["live-source:Plane of Hate"])
    for key in ("w9843", "w9844", "w9845"):  # a stated NONE is nobody: not for best-in-slot, at the level the sources give
        assert level_and_codes(items[key]) == ("wiki", ["live-source:Plane of Hate", "not-for-bis"]), key
    text = {key: {r["code"]: r["text"] for r in items[key]["evidence"]["reasons"]}["not-for-bis"] for key in ("w9843", "w9844", "w9845")}
    assert "race NONE" in text["w9843"] and "class NONE" not in text["w9843"]
    assert "class NONE" in text["w9844"] and "race NONE" not in text["w9844"]
    assert "class NONE and race NONE" in text["w9845"]
    assert summary["warnings"]["parse_by_code"] == {"no-classes": 4}  # one per stated NONE; nothing for the missing line


# ---- a hand weapon that cannot be scored --------------------------------------------------------------------------


def test_a_hand_weapon_with_a_skill_but_no_damage_is_warned_and_not_for_bis_in_the_catalog(tmp_path, quests_file):
    drops = "[[Plane of Hate]]"
    sword = "Slot: PRIMARY<br>\nSkill: 2H Slashing<br>\nAtk Delay: 40<br>\n"
    records = [
        synthetic_record(9861, "Zorblax Greatsword", statsblock=sword + "Race: ALL", dropsfrom=drops),  # no damage
        synthetic_record(9862, "Quuxen Greatsword", statsblock=sword + "DMG: 20<br>\nRace: ALL", dropsfrom=drops),
        synthetic_record(9863, "Blarg Arrow", statsblock="Slot: AMMO<br>\nSkill: Archery<br>\nDMG: 7<br>\nRace: ALL", dropsfrom=drops),
    ]
    summary, out = build(tmp_path, records, quests_file)
    items = items_by_key(out)
    assert level_and_codes(items["w9861"]) == ("wiki", ["live-source:Plane of Hate", "not-for-bis"])
    assert level_and_codes(items["w9862"]) == ("wiki", ["live-source:Plane of Hate"])
    assert level_and_codes(items["w9863"]) == ("wiki", ["live-source:Plane of Hate"])  # ammo has no delay
    listed = read_json(out / "catalog-warnings.json")["warnings"]
    assert [w for w in listed if w["code"] == "weapon-incomplete"] == [{"key": "w9861", "code": "weapon-incomplete", "field": "weapon"}]
    assert summary["warnings"]["parse_by_code"] == {"weapon-incomplete": 1}


def test_every_item_of_a_built_catalog_validates_against_the_item_schema(tmp_path, quests_file):
    titles = ["Engineer's Ring", "Girdle of Faith", "Cloak of Flames", "Darkwar Mask", "Mask of Deception", "Backpack", "Bone Chips", "Banded Belt"]
    _, out = build(tmp_path, [fixture_record(title) for title in titles], quests_file)
    validate_catalog(read_json(out / "catalog.json"))


def test_validate_catalog_refuses_a_document_that_is_not_a_catalog(tmp_path, quests_file):
    _, out = build(tmp_path, [fixture_record("Engineer's Ring"), fixture_record("Girdle of Faith")], quests_file)
    good = read_json(out / "catalog.json")
    for edit in (
        lambda d: d["items"].reverse(),
        lambda d: d.update(license="MIT"),
        lambda d: d["items"][0].pop("evidence"),
        lambda d: d["items"].append(copy.deepcopy(d["items"][0])),
        lambda d: d["items"][0].update(extra=1),
        lambda d: d["items"][0]["evidence"].update(level="maybe"),
        lambda d: d.pop("attribution"),
    ):
        bad = copy.deepcopy(good)
        edit(bad)
        with pytest.raises(Exception):
            validate_catalog(bad)


# ---- the items that carry strict evidence are invented ----------------------------------------------------------------

# A seen flag, a community report and a listed catalog key put an item at the strict level. A public test that did that to a recorded page of
# a real item would read as a statement about the game, so every test that does it builds invented items: a page id, a title and a revision
# that no page of the wiki has (the id is far above the ids of the committed catalog).
FLAGGED_PAGE, BYSTANDER_PAGE = 910001, 910002
FLAGGED_KEY, BYSTANDER_KEY = f"w{FLAGGED_PAGE}", f"w{BYSTANDER_PAGE}"
FLAG_MARKERS = frozenset({"seen_file", "seen_path", "catalog_keys_allowed", "community-seen.json", "seen-flags.json", "--seen"})
RECORDED_PAGE = "fixture_record"


def flagged_record():
    """The invented item that the tests below flag by key: a ring that drops in the Plane of Hate, so that a flag is what lifts it from the wiki level."""
    return synthetic_record(FLAGGED_PAGE, "Zorblax Signet", statsblock="Slot: FINGER", dropsfrom="[[Plane of Hate]]")


def bystander_record():
    """The invented item built beside it, which no flag names."""
    return synthetic_record(BYSTANDER_PAGE, "Quuxen Signet", statsblock="Slot: FINGER", dropsfrom="[[Plane of Hate]]")


def test_no_test_that_flags_an_item_builds_a_recorded_page_of_a_real_item():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    both = []
    for test in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
        mentioned = {node.id for node in ast.walk(test) if isinstance(node, ast.Name)}
        mentioned |= {node.arg for node in ast.walk(test) if isinstance(node, ast.keyword) and node.arg}
        mentioned |= {node.value for node in ast.walk(test) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        if mentioned & FLAG_MARKERS and RECORDED_PAGE in mentioned:
            both.append(test.name)
    assert both == []


@pytest.mark.skipif(not (REPO / "derived" / "catalog.json").is_file(), reason="derived/catalog.json is not built")
def test_the_invented_items_are_no_item_of_the_committed_catalog():
    items = read_json(REPO / "derived" / "catalog.json")["items"]
    taken = {item["key"] for item in items} | {item["name"] for item in items} | {item["wiki"]["title"] for item in items}
    revisions = {item["wiki"]["revid"] for item in items}
    newest = max(item["wiki"]["pageid"] for item in items)
    for record in (flagged_record(), bystander_record()):
        found = (f"w{record['pageid']}" in taken, record["title"] in taken, record["revid"] in revisions)
        assert not any(found), found  # a key, a title and a revision that a real page has
        assert record["pageid"] > newest  # above every page of the catalog, so the next page the wiki adds is not one of these


def test_community_reports_make_items_strict_and_unknown_keys_are_counted(tmp_path, quests_file):
    rules = tmp_path / "rules"
    shutil.copytree(RULES, rules)
    report = {"version": DATE, "reports": [
        {"key": FLAGGED_KEY, "kind": "seen", "issue": 1, "date": DATE, "check": "item-window-screenshot"},
        {"key": "w999999", "kind": "tier", "issue": 2, "date": DATE, "check": "item-window-screenshot"},
    ], "retracted": [
        {"key": BYSTANDER_KEY, "issue": 3, "date": DATE, "reason": "wrong-item"},
    ]}  # fmt: skip
    (rules / "community-seen.json").write_text(json.dumps(report), encoding="utf-8")
    summary, out = build(tmp_path, [flagged_record(), bystander_record()], quests_file, rules=rules)
    items = items_by_key(out)
    assert level_and_codes(items[FLAGGED_KEY]) == ("strict", ["community-report"])
    assert level_and_codes(items[BYSTANDER_KEY])[0] == "wiki"  # (its report was retracted: an entry of "retracted" gives no key)
    assert summary["community_unknown"] == 1 and summary["counts"]["by_level"]["strict"] == 1
    provenance = read_json(out / "catalog.json")["provenance"]
    assert "rules/community-seen.json" in [record["file"] for record in provenance["inputs"]]


def test_a_report_for_an_item_the_wiki_marks_as_gone_leaves_it_hidden_and_a_report_for_a_live_item_makes_it_strict(tmp_path, quests_file):
    rules = tmp_path / "rules"
    shutil.copytree(RULES, rules)
    marked = plain_record(FLAGGED_PAGE, "Zorblax Signet", "{{delete}}\n" + flagged_record()["content"])  # a live source, and the banner that says the page was deleted
    removed = synthetic_record(910003, "Blarg Signet", statsblock="Slot: FINGER", dropsfrom="ITEM REMOVED FROM GAME")
    live = bystander_record()
    reports = [{"key": f"w{page}", "kind": "seen", "issue": number, "date": DATE, "check": "item-window-screenshot"} for number, page in enumerate((FLAGGED_PAGE, 910003, BYSTANDER_PAGE), 1)]
    (rules / "community-seen.json").write_text(json.dumps({"version": DATE, "reports": reports, "retracted": []}), encoding="utf-8")
    summary, out = build(tmp_path, [marked, removed, live], quests_file, rules=rules)
    items = items_by_key(out)
    assert level_and_codes(items[FLAGGED_KEY]) == ("hidden", ["community-report-outweighed", "wiki-marked-not-in-eql"])
    assert level_and_codes(items["w910003"]) == ("hidden", ["community-report-outweighed", "wiki-marked-removed"])
    assert level_and_codes(items[BYSTANDER_KEY]) == ("strict", ["community-report"])
    assert summary["counts"]["by_level"]["strict"] == 1 and summary["community_unknown"] == 0
    assert "conflict-note" not in summary["counts"]["by_reason"]  # (nothing is kept as strict against the wiki's word)
    counts = summary["counts"]
    assert counts["by_reason"]["community-report-outweighed"] == 2  # both hidden items carry it ...
    assert counts["hidden_by_reason"] == {"wiki-marked-not-in-eql": 1, "wiki-marked-removed": 1}  # ... and it is no reason to hide an item: only the marks hide them


def test_the_allowed_catalog_keys_make_items_strict(tmp_path, quests_file):
    _, out = build(tmp_path, [flagged_record()], quests_file, catalog_keys_allowed=[FLAGGED_KEY])
    assert level_and_codes(items_by_key(out)[FLAGGED_KEY]) == ("strict", ["eql-catalog"])


@pytest.mark.parametrize(
    "document",
    [[], {}, {"reports": "x"}, {"reports": [{"key": "w1"}]}, {"reports": [{"key": "bad key", "issue": "https://x.invalid/1"}]},
     {"reports": [{"key": "w1", "issue": "http://x.invalid/1"}]}, {"reports": ["w1"]}],
)
def test_a_damaged_community_file_is_refused(tmp_path, document):
    path = tmp_path / "community-seen.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(BuildError):
        load_community_keys(path)


def test_no_community_file_means_no_community_keys(tmp_path):
    assert load_community_keys(tmp_path / "nothing.json") == frozenset()


# ---- seen flags never reach a committed build -----------------------------------------------------------


def seen_file(tmp_path, keys=(FLAGGED_KEY, "w1")):
    path = tmp_path / "seen" / "seen-flags.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"version": DATE, "license": "CC BY-SA 4.0", "keys": sorted(keys)}), encoding="utf-8")
    return path


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    root = tmp_path / "fake-repo"
    for name in ("derived", "build", "docs", "sources"):
        (root / name).mkdir(parents=True)
    monkeypatch.setattr(catalog, "REPO_ROOT", root)
    return root


def test_seen_flags_are_merged_only_into_a_build_outside_derived(tmp_path, quests_file, fake_repo):
    out = tmp_path / "private-preview"
    summary, _ = build(tmp_path, [flagged_record(), bystander_record()], quests_file, out=out, seen_path=seen_file(tmp_path))
    items = items_by_key(out)
    assert level_and_codes(items[FLAGGED_KEY]) == ("strict", ["seen-in-game"])
    assert level_and_codes(items[BYSTANDER_KEY])[0] == "wiki"
    assert summary["seen"] == {"keys": 2, "unknown": 1}
    assert list((fake_repo / "derived").iterdir()) == []


def test_a_catalog_built_with_seen_flags_is_refused_by_the_keyless_scan_under_any_path(tmp_path, quests_file, fake_repo):
    """The guard keeps a seen build out of tracked folders; if one is committed anyway, the scan that CI runs says so."""
    records = [flagged_record(), bystander_record()]
    _, seen_out = build(tmp_path / "with", records, quests_file, out=tmp_path / "private-preview", seen_path=seen_file(tmp_path))
    _, plain_out = build(tmp_path / "without", records, quests_file)
    flagged, plain = (seen_out / "catalog.json").read_bytes(), (plain_out / "catalog.json").read_bytes()
    for path in ("derived/catalog.json", "build/catalog-with-seen/catalog.json", "docs/anything.json", "x.JSON", "a/b/c.jsonl"):
        assert "seen-reason" in [found.rule for found in scan_bytes(path, flagged, None, set(), set())], path
        assert scan_bytes(path.replace("build/", "out/"), plain, None, set(), set()) == [], path  # the same build without the flags is clean


@pytest.mark.parametrize(
    "where",
    ["derived", "derived/sub", ".", "docs", "sources/eqlwiki", "build/../derived", "buildx", "build/../buildx/y", "derived/../derived/x"],
)
def test_a_seen_build_into_a_tracked_folder_is_refused_before_anything_is_read_or_written(tmp_path, quests_file, fake_repo, where):
    out = fake_repo / where
    before = sorted(str(p) for p in fake_repo.rglob("*"))
    with pytest.raises(BuildError, match="refused"):
        build_catalog(tmp_path / "no-such-wiki", tmp_path / "no-such-client", out, seen_path=tmp_path / "no-such-seen.json", workers=0)
    assert sorted(str(p) for p in fake_repo.rglob("*")) == before


@pytest.mark.parametrize("where", ["build", "build/catalog-with-seen", "build/a/b/c", "build/../build/x"])
def test_a_seen_build_into_build_is_allowed(tmp_path, quests_file, fake_repo, where):
    out = fake_repo / where
    build(tmp_path, [flagged_record()], quests_file, out=out, seen_path=seen_file(tmp_path))
    assert (Path(os.path.realpath(out)) / "catalog.json").is_file()


def test_a_seen_build_outside_the_repository_is_allowed(tmp_path, quests_file, fake_repo):
    out = tmp_path / "elsewhere" / "preview"
    build(tmp_path, [flagged_record()], quests_file, out=out, seen_path=seen_file(tmp_path))
    assert (out / "catalog.json").is_file()


def test_a_link_inside_build_that_points_at_derived_is_refused(tmp_path, fake_repo):
    link = fake_repo / "build" / "link"
    try:
        os.symlink(fake_repo / "derived", link, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Windows lets anyone make a directory junction, which resolves the same way
        made = os.name == "nt" and subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(fake_repo / "derived")], capture_output=True).returncode == 0
        if not made:
            pytest.skip("this system does not let the test make a link")
    with pytest.raises(BuildError, match="refused"):
        check_seen_output(link / "out")
    with pytest.raises(BuildError, match="refused"):
        check_seen_output(link)


def test_without_seen_flags_the_output_may_be_anywhere(tmp_path, quests_file, fake_repo):
    _, out = build(tmp_path, [fixture_record("Engineer's Ring")], quests_file, out=fake_repo / "derived")
    assert (out / "catalog.json").is_file()
    assert "seen-in-game" not in (out / "catalog.json").read_text(encoding="utf-8")


def test_the_default_output_of_a_seen_build_is_build_catalog_with_seen(tmp_path, quests_file, fake_repo, capsys):
    wiki = make_wiki(tmp_path / "wiki", [flagged_record()])
    argv = ["--wiki", str(wiki), "--client", str(CLIENT), "--quests", str(quests_file), "--rules", str(RULES), "--date", DATE, "--workers", "0"]
    assert main([*argv, "--seen", str(seen_file(tmp_path))]) == 0
    assert (fake_repo / "build" / "catalog-with-seen" / "catalog.json").is_file()
    assert list((fake_repo / "derived").iterdir()) == []
    capsys.readouterr()
    assert main([*argv, "--seen", str(seen_file(tmp_path)), "--out", str(fake_repo / "derived")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "refused" in err and err.count("\n") == 1
    assert list((fake_repo / "derived").iterdir()) == []


def test_the_default_output_without_seen_flags_is_derived(tmp_path, quests_file, fake_repo):
    wiki = make_wiki(tmp_path / "wiki", [fixture_record("Engineer's Ring")])
    argv = ["--wiki", str(wiki), "--client", str(CLIENT), "--quests", str(quests_file), "--rules", str(RULES), "--date", DATE, "--workers", "0"]
    assert main(argv) == 0
    assert sorted(p.name for p in (fake_repo / "derived").iterdir()) == sorted(OUTPUT_FILES)


@pytest.mark.parametrize(
    "document",
    [[], {}, {"keys": "w1"}, {"keys": ["w1", 2]}, {"keys": ["w1 "]}, {"keys": ["x1"]}, {"keys": ["w" + "9" * 40]}],
)
def test_a_damaged_seen_file_is_refused(tmp_path, document):
    path = tmp_path / "seen-flags.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(BuildError):
        load_seen_keys(path)


def test_the_seen_file_may_carry_version_and_license_besides_the_keys(tmp_path):
    assert load_seen_keys(seen_file(tmp_path, keys=["w2", "rzorblax-ring", "w1"])) == {"w1", "w2", "rzorblax-ring"}


def test_the_summary_of_a_build_without_seen_flags_says_nothing_about_them(tmp_path, quests_file):
    summary, out = build(tmp_path, [fixture_record("Engineer's Ring")], quests_file)
    assert "seen" not in summary
    for name in OUTPUT_FILES:
        assert "seen" not in (out / name).read_text(encoding="utf-8").lower().replace("unseen", "")


# ---- the committed files ----------------------------------------------------------------------------------


@pytest.mark.skipif(not (REPO / "derived" / "catalog.json").is_file(), reason="derived/catalog.json is not built")
def test_the_committed_catalog_has_no_seen_in_game_reason_and_strict_only_from_community_reports():
    document = read_json(REPO / "derived" / "catalog.json")
    assert document["license"] == "CC BY-SA 4.0" and document["attribution"] == ATTRIBUTION
    keys = [item["key"] for item in document["items"]]
    assert keys == sorted(keys) and len(keys) == len(set(keys))
    for item in document["items"]:
        found = [reason["code"] for reason in item["evidence"]["reasons"]]
        assert "seen-in-game" not in found
        if item["evidence"]["level"] == "strict":
            assert "community-report" in found or "eql-catalog" in found
    text = (REPO / "derived" / "catalog.json").read_text(encoding="utf-8")
    assert "seen-in-game" not in text
    assert "seen" not in read_json(REPO / "derived" / "catalog-summary.json")
    manifest = read_json(REPO / "derived" / "sources-manifest.json")
    assert list(manifest["items"]) == keys


@pytest.mark.skipif(not (REPO / "derived" / "catalog.json").is_file(), reason="derived/catalog.json is not built")
def test_the_committed_catalog_types_the_shields_by_the_rules_and_says_where_each_type_came_from():
    document = read_json(REPO / "derived" / "catalog.json")
    lists = read_json(RULES / "hand-lists.json")
    shields = {entry["key"] for entry in lists["shields"]}
    vetoed = {entry["key"] for entry in lists["not_shields"]}
    name_rule = re.compile(r"shield|buckler|aegis|bulwark|targe", re.IGNORECASE)  # written out: not the builder's constant
    by_source = {"statsblock": 0, "name": 0, "hand-list": 0}
    for item in document["items"]:
        key, kind, source = item["key"], item["item_type"], item["item_type_source"]
        assert (kind is None) == (source is None), key  # a type says where it came from, and only a type has a source
        by_name = (
            "SECONDARY" in item["slots"]
            and set(item["slots"]) <= {"SECONDARY", "BACK"}  # the off hand, alone or with the back
            and item["weapon"] is None
            and (item["stats"].get("AC") or 0) > 0
            and name_rule.search(item["name"]) is not None
        )
        if key in vetoed:
            assert kind is None, key
        elif source == "statsblock":
            assert kind, key  # the page states it
        elif by_name:
            assert (kind, source) == ("Shield", "name"), key
        elif key in shields:
            assert (kind, source) == ("Shield", "hand-list"), key
        else:
            assert (kind, source) == (None, None), key
        if kind == "Shield":
            by_source[source] += 1
    assert by_source["hand-list"] == len(shields)  # every hand-listed shield is one that no rule catches
    summary = read_json(REPO / "derived" / "catalog-summary.json")["item_types"]
    assert summary["shield_by_source"] == by_source
    assert summary["shield_vetoed"] == len(vetoed) and summary["hand_list_stale"] == 0


@pytest.mark.skipif(not (REPO / "derived" / "catalog.json").is_file(), reason="derived/catalog.json is not built")
def test_the_committed_catalog_has_the_hand_listed_shields_and_not_the_three_held_items():
    by_name = {item["name"]: item for item in read_json(REPO / "derived" / "catalog.json")["items"]}

    def types(name):
        return by_name[name]["item_type"], by_name[name]["item_type_source"]

    for name in (
        "Life's Guard", "Marr's Promise", "Insignia Protector", "Bladestopper", "Krup Warrior Guard",
        "Guard of the Marines", "Guard of Ik", "Devlas Ilkvel", "Nisch Mas Ilkvel",
    ):  # fmt: skip
        assert types(name) == ("Shield", "hand-list"), name
    for name in ("Cryosilk Webshield", "Crystal Webshield", "Shield of the Devout"):  # held, vetoed although the name says shield
        assert types(name) == (None, None), name
    assert types("Shield of the Stalwart Seas") == ("Shield", "statsblock")
    assert types("Crushbone Fetish") == ("Shield", "statsblock")  # its page says Skill: SHIELD
    assert types("Small Shield") == ("Shield", "name") and types("Aegis of Ice") == ("Shield", "name")
    assert types("Spiked Buckler") == ("Shield", "name")  # a buckler with a focus effect: the wiki files it under Focus Items
    for name in ("Aegis of Life", "Dark Shield of Ebon", "Shield of the Immaculate", "Silent Watch Shield"):
        assert by_name[name]["slots"] == ["BACK", "SECONDARY"] and types(name) == ("Shield", "name"), name  # fits the back too
    assert types("Shield of the Slain Unicorn") == (None, None)  # its page gives weapon numbers
    assert types("Stave of Shielding") == (None, None)  # a staff for the main hand
    assert types("Engineer's Ring") == (None, None)


@pytest.mark.skipif(not (REPO / "derived" / "catalog.json").is_file(), reason="derived/catalog.json is not built")
def test_the_committed_catalog_keeps_the_empty_lists_of_the_none_pages_and_marks_them_not_for_bis_with_the_note():
    document = read_json(REPO / "derived" / "catalog.json")
    empty_races = empty_classes = 0
    for item in document["items"]:
        notes = {reason["code"]: reason["text"] for reason in item["evidence"]["reasons"]}
        for field, warned_field, label in (("races", "race", "race NONE"), ("classes", "class", "class NONE")):
            if item[field] == []:  # only a page that says NONE: nobody may wear or use the item
                assert {"code": "no-classes", "field": warned_field} in item["parse_warnings"], item["key"]
                assert label in notes["not-for-bis"], item["key"]
                if field == "races":
                    empty_races += 1
                else:
                    empty_classes += 1
    assert empty_races > 0 and empty_classes > 0
    codes = read_json(REPO / "derived" / "catalog-summary.json")["warnings"]["parse_by_code"]
    assert "no-races" not in codes and codes["no-classes"] == empty_races + empty_classes


@pytest.mark.skipif(not (REPO / "derived" / "catalog.json").is_file(), reason="derived/catalog.json is not built")
def test_the_committed_catalog_has_no_hand_weapon_that_cannot_be_scored_and_keg_mallet_has_its_damage():
    document = read_json(REPO / "derived" / "catalog.json")
    for item in document["items"]:
        weapon = item["weapon"]
        incomplete = weapon is not None and weapon["skill"] is not None and (weapon["dmg"] is None or weapon["delay"] is None)
        if incomplete:  # ammunition has no delay, a bow is not held in a hand
            assert not set(item["slots"]) & {"PRIMARY", "SECONDARY"}, item["key"]
        assert {"code": "weapon-incomplete", "field": "weapon"} not in item["parse_warnings"], item["key"]
    keg = next(item for item in document["items"] if item["name"] == "Keg Mallet")
    assert keg["weapon"] == {"skill": "1H Blunt", "dmg": 9, "delay": 30, "bonus": None}  # its page says "Base Dmg: 9"
    assert "weapon-incomplete" not in read_json(REPO / "derived" / "catalog-summary.json")["warnings"]["parse_by_code"]


# ---- refusing what cannot be trusted --------------------------------------------------------------------


@pytest.fixture
def client_copy(tmp_path):
    target = tmp_path / "client"
    shutil.copytree(CLIENT, target)
    return target


def edit_json(path, edit):
    document = read_json(path)
    edit(document)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_a_client_extract_from_a_different_patch_is_refused_naming_the_file(tmp_path, quests_file, client_copy):
    def patch(document):
        document["provenance"]["inputs"][0]["sha256"] = "0" * 64

    edit_json(client_copy / "zones.json", patch)
    with pytest.raises(BuildError) as caught:
        build(tmp_path, [fixture_record("Engineer's Ring")], quests_file, client=client_copy)
    message = str(caught.value)
    assert "zones.json" in message and "Resources/ZoneNames.txt" in message and "patched" in message
    assert not (tmp_path / "out").exists()


def test_the_file_named_is_the_one_that_changed_not_the_one_the_build_reads(tmp_path, quests_file, client_copy):
    edit_json(client_copy / "basedata.json", lambda d: d["provenance"]["inputs"][0].update(sha256="f" * 64))
    with pytest.raises(BuildError) as caught:
        build(tmp_path, [fixture_record("Engineer's Ring")], quests_file, client=client_copy)
    assert "basedata.json" in str(caught.value) and "zones.json" not in str(caught.value)


def test_a_manifest_that_moved_on_to_a_new_patch_refuses_the_old_extracts(tmp_path, quests_file, client_copy):
    def moved_on(document):
        for record in document["inputs"]:
            if record["file"] == "Resources/ZoneNames.txt":
                record["sha256"] = "a" * 64

    edit_json(client_copy / "manifest.json", moved_on)
    with pytest.raises(BuildError, match="zones.json"):
        build(tmp_path, [fixture_record("Engineer's Ring")], quests_file, client=client_copy)


def test_the_check_goes_by_hash_never_by_modification_time(tmp_path, quests_file, client_copy):
    for path in client_copy.iterdir():
        os.utime(path, (1_000_000_000, 1_000_000_000))
    check_client(client_copy)
    _, out = build(tmp_path, [fixture_record("Engineer's Ring")], quests_file, client=client_copy)
    assert (out / "catalog.json").is_file()


@pytest.mark.parametrize("missing", ["manifest.json", "zones.json", "spells-l55.json", "skillcaps.json"])
def test_a_missing_client_file_is_refused_and_named(tmp_path, quests_file, client_copy, missing):
    (client_copy / missing).unlink()
    with pytest.raises(BuildError, match=missing):
        build(tmp_path, [fixture_record("Engineer's Ring")], quests_file, client=client_copy)


def test_a_client_extract_whose_manifest_does_not_list_the_zones_is_refused(tmp_path, quests_file, client_copy):
    edit_json(client_copy / "manifest.json", lambda d: d.update(outputs=[o for o in d["outputs"] if o["file"] != "zones.json"]))
    with pytest.raises(BuildError, match="zones.json"):
        build(tmp_path, [fixture_record("Engineer's Ring")], quests_file, client=client_copy)


def test_a_client_extract_that_records_no_hashes_is_refused(tmp_path, quests_file, client_copy):
    edit_json(client_copy / "zones.json", lambda d: d["provenance"].update(inputs=[]))
    with pytest.raises(BuildError, match="zones.json"):
        build(tmp_path, [fixture_record("Engineer's Ring")], quests_file, client=client_copy)


def test_the_command_line_ends_with_exit_status_two_and_one_line_for_a_patched_client(tmp_path, quests_file, client_copy, capsys):
    edit_json(client_copy / "zones.json", lambda d: d["provenance"]["inputs"][0].update(sha256="0" * 64))
    wiki = make_wiki(tmp_path / "wiki", [fixture_record("Engineer's Ring")])
    code = main(["--wiki", str(wiki), "--client", str(client_copy), "--out", str(tmp_path / "out"), "--quests", str(quests_file), "--workers", "0"])
    err = capsys.readouterr().err
    assert code == 2 and err.startswith("error: ") and err.count("\n") == 1 and "zones.json" in err
    assert not (tmp_path / "out").exists()


def test_an_unfinished_fetch_is_refused(tmp_path, quests_file):
    wiki = make_wiki(tmp_path / "wiki", [fixture_record("Engineer's Ring")])
    (wiki / "manifest.json").unlink()  # the fetcher writes it last
    with pytest.raises(BuildError, match="manifest.json"):
        build_catalog(wiki, CLIENT, tmp_path / "out", quests_path=quests_file, workers=0)
    assert not (tmp_path / "out").exists()


def test_a_missing_or_damaged_batch_file_is_refused(tmp_path, quests_file):
    records = [synthetic_record(10000 + n, f"Zorblax Ring {n}") for n in range(120)]  # three batches
    wiki = make_wiki(tmp_path / "wiki", records)
    batch = wiki / "raw" / "batch-0001.json.gz"
    batch.write_bytes(batch.read_bytes()[:20])
    with pytest.raises(BuildError, match="batch-0001"):
        build_catalog(wiki, CLIENT, tmp_path / "out", quests_path=quests_file, workers=0)
    batch.unlink()
    with pytest.raises(BuildError, match="batch-0001"):
        build_catalog(wiki, CLIENT, tmp_path / "out", quests_path=quests_file, workers=0)


def test_a_batch_that_holds_other_pages_than_the_member_list_says_is_refused(tmp_path, quests_file):
    wiki = make_wiki(tmp_path / "wiki", [synthetic_record(10001, "Zorblax Ring"), synthetic_record(10002, "Quuxen Ring")])
    batch = wiki / "raw" / "batch-0000.json.gz"
    data = json.loads(gzip.decompress(batch.read_bytes()))
    data["pages"].reverse()
    batch.write_bytes(gzip.compress(json.dumps(data).encode("ascii"), mtime=0))
    with pytest.raises(BuildError, match="batch-0000"):
        read_wiki(wiki)


def test_a_manifest_that_disagrees_with_the_member_list_is_refused(tmp_path):
    wiki = make_wiki(tmp_path / "wiki", [synthetic_record(10001, "Zorblax Ring")])
    manifest = read_json(wiki / "manifest.json")
    manifest["members"] = 5
    (wiki / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BuildError, match="disagrees"):
        read_wiki(wiki)


def test_the_wiki_snapshot_hash_depends_on_every_batch_and_the_member_list(tmp_path):
    records = [synthetic_record(10000 + n, f"Zorblax Ring {n}") for n in range(60)]
    first = read_wiki(make_wiki(tmp_path / "a", records))
    assert read_wiki(make_wiki(tmp_path / "b", records)).sha256 == first.sha256
    changed = [dict(records[0], content=records[0]["content"] + " ")] + records[1:]
    assert read_wiki(make_wiki(tmp_path / "c", changed)).sha256 != first.sha256
    assert first.date == DATE and first.category == "Category:Items" and len(first.pages) == 60


@pytest.mark.parametrize("missing", ["quests", "hand-lists", "aliases"])
def test_a_missing_derived_or_rules_input_is_refused(tmp_path, quests_file, missing):
    rules = tmp_path / "rules"
    shutil.copytree(RULES, rules)
    quests = quests_file
    if missing == "quests":
        quests = tmp_path / "nothing.json"
    elif missing == "hand-lists":
        (rules / "hand-lists.json").unlink()
    else:
        (rules / "zone-aliases.json").unlink()
    with pytest.raises(BuildError, match="missing"):
        build(tmp_path, [fixture_record("Engineer's Ring")], quests, rules=rules)
    assert not (tmp_path / "out").exists()


def test_an_alias_to_a_zone_the_client_does_not_have_is_refused(tmp_path, quests_file):
    rules = tmp_path / "rules"
    shutil.copytree(RULES, rules)
    edit_json(rules / "zone-aliases.json", lambda d: d["aliases"].update({"zorblax hollow": [123456]}))
    with pytest.raises(BuildError, match="zone-aliases.json"):
        build(tmp_path, [fixture_record("Engineer's Ring")], quests_file, rules=rules)


def test_a_failed_build_leaves_the_old_files_as_they_were(tmp_path, quests_file, client_copy):
    out = tmp_path / "out"
    out.mkdir()
    for name in OUTPUT_FILES:
        (out / name).write_text("old", encoding="utf-8")
    edit_json(client_copy / "zones.json", lambda d: d["provenance"]["inputs"][0].update(sha256="0" * 64))
    with pytest.raises(BuildError):
        build(tmp_path, [fixture_record("Engineer's Ring")], quests_file, client=client_copy, out=out)
    assert {name: (out / name).read_text(encoding="utf-8") for name in OUTPUT_FILES} == dict.fromkeys(OUTPUT_FILES, "old")


# ---- time limits ------------------------------------------------------------------------------------------


def test_a_page_that_hangs_crashes_or_raises_is_skipped_and_the_rest_are_built(tmp_path, quests_file, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent))  # the workers import _targets from here
    records = [
        fixture_record("Engineer's Ring"),
        synthetic_record(9901, "Slow Page"),
        synthetic_record(9902, "Crash Page"),
        synthetic_record(9903, "Raise Page"),
        fixture_record("Girdle of Faith"),
    ]
    summary, out = build(tmp_path, records, quests_file, workers=2, timeout=4.0, target="_targets:target")
    assert summary["counts"]["skipped"] == {"error": 2, "timeout": 1}
    assert list(items_by_key(out)) == ["w16279", "w42638"]
    skipped = {s["pageid"]: s["reason"] for s in read_json(out / "catalog-warnings.json")["skipped"]}
    assert skipped == {9901: "timeout", 9902: "error", 9903: "error"}


def test_the_time_limit_does_not_count_the_time_a_worker_takes_to_start(tmp_path, quests_file):
    # with a limit far below the time a worker needs to import the parser, every page must still be read
    records = [fixture_record("Engineer's Ring"), fixture_record("Girdle of Faith")]
    summary, _ = build(tmp_path, records, quests_file, workers=1, timeout=3.0)
    assert summary["counts"]["items"] == 2 and summary["counts"]["skipped"] == {}


def test_worker_processes_give_the_same_catalog_as_parsing_in_this_process(tmp_path, quests_file):
    records = [fixture_record(t) for t in ("Engineer's Ring", "Girdle of Faith", "Darkwar Mask", "Backpack")]
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _, one = build(tmp_path / "a", records, quests_file, workers=0)
    _, two = build(tmp_path / "b", records, quests_file, workers=2)
    assert (one / "catalog.json").read_bytes() == (two / "catalog.json").read_bytes()


# ---- the same bytes every time --------------------------------------------------------------------------------


def test_the_build_gives_identical_bytes_whatever_the_hash_seed_and_the_worker_count(tmp_path, quests_file):
    titles = ["Engineer's Ring", "Girdle of Faith", "Cloak of Flames", "Darkwar Mask", "Mask of Deception", "Backpack", "Banded Belt", "Ogre Bouncer Shield"]
    wiki = make_wiki(tmp_path / "wiki", [fixture_record(title) for title in titles])
    outputs = []
    for seed, workers in (("1", "0"), ("2", "2")):
        out = tmp_path / f"out{seed}"
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(REPO / "pipeline"))
        result = subprocess.run(
            [sys.executable, "-m", "trioforge.data.catalog", "--wiki", str(wiki), "--client", str(CLIENT), "--out", str(out),
             "--quests", str(quests_file), "--date", DATE, "--workers", workers],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=600,
        )  # fmt: skip
        assert result.returncode == 0, result.stderr
        outputs.append({name: (out / name).read_bytes() for name in OUTPUT_FILES})
    assert outputs[0] == outputs[1]


def test_the_order_of_the_pages_does_not_change_the_items(tmp_path, quests_file):
    records = [fixture_record(t) for t in ("Engineer's Ring", "Girdle of Faith", "Darkwar Mask", "Backpack", "Rusty Dagger")]
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _, forward = build(tmp_path / "a", records, quests_file)
    _, backward = build(tmp_path / "b", records[::-1], quests_file)
    assert read_json(forward / "catalog.json")["items"] == read_json(backward / "catalog.json")["items"]


# ---- hostile text -------------------------------------------------------------------------------------------


def test_a_lone_surrogate_in_a_page_never_reaches_the_catalog_file(tmp_path, quests_file):
    hostile = synthetic_record(9951, "Zorblax Ring")
    hostile["content"] = hostile["content"].replace("Zorblax Ring", "Zorblax \ud800 Ring \udfff", 1)
    hostile["title"] = "Zorblax \ud800 Ring"
    _, out = build(tmp_path, [hostile, fixture_record("Engineer's Ring")], quests_file)
    data = (out / "catalog.json").read_bytes()
    text = data.decode("utf-8")  # strict: a lone surrogate would not even encode
    assert not any("\ud800" <= char <= "\udfff" for char in text)
    assert "Zorblax  Ring" in text or "Zorblax Ring" in text


def test_markup_in_names_never_reaches_the_files(tmp_path, quests_file):
    hostile = synthetic_record(9952, "Ring<script>alert(1)</script>‮", dropsfrom="[[Plane of Hate<b>]]\n* [[<i>Boss</i>]]")
    _, out = build(tmp_path, [hostile], quests_file)
    for name in OUTPUT_FILES:
        text = (out / name).read_text(encoding="utf-8")
        assert "<" not in text and ">" not in text and "‮" not in text, name


def test_the_command_line_prints_totals_and_no_item_names(tmp_path, quests_file, capsys):
    wiki = make_wiki(tmp_path / "wiki", [fixture_record("Engineer's Ring"), fixture_record("Girdle of Faith"), fixture_record("Rusty Dagger")])
    code = main(["--wiki", str(wiki), "--client", str(CLIENT), "--out", str(tmp_path / "out"), "--quests", str(quests_file), "--date", DATE, "--workers", "0"])
    printed = capsys.readouterr().out
    assert code == 0
    assert "3 items" in printed and "by level: strict 0, wiki 3, disputed 0, hidden 0" in printed
    for name in ("Engineer", "Girdle", "Rusty", "Innoruuk"):
        assert name not in printed


def test_a_bad_date_is_a_usage_error(tmp_path, quests_file):
    with pytest.raises(SystemExit) as caught:
        main(["--wiki", str(tmp_path), "--client", str(CLIENT), "--date", "2026-02-30"])
    assert caught.value.code == 2


# ---- the whole cached pull (skipped where the git-ignored cache is absent) -------------------------------------

CACHES = sorted((REPO / "sources" / "eqlwiki").glob("*/manifest.json"))
CACHE_READY = bool(CACHES) and (REPO / "derived" / "quests.json").is_file()
HIDDEN_CODES = {
    "removed-by-patch",
    "removed-by-research",
    "zone-unreleased",
    "zones-unmapped",
    "zones-not-in-eql",
    "out-of-era",
    "cultural-container",
    "out-of-era-ingredient",
    "no-known-source",
    "wiki-marked-not-in-eql",
    "wiki-marked-removed",
}


@pytest.fixture(scope="module")
def real_build(tmp_path_factory):
    import time

    out = tmp_path_factory.mktemp("real-build")
    start = time.perf_counter()
    summary = build_catalog(CACHES[-1].parent, CLIENT, out, quests_path=REPO / "derived" / "quests.json", generated=DATE, workers=4)
    return summary, out, time.perf_counter() - start


@pytest.mark.skipif(not CACHES, reason="needs the cached wiki pull (sources/eqlwiki/<date>, git-ignored)")
def test_every_page_of_the_cached_pull_normalizes_to_an_item_that_validates_against_the_schema():
    snapshot = read_wiki(CACHES[-1].parent)
    items = skipped = 0
    for page in snapshot.pages:
        kind, found = catalog.parse_and_normalize(page)  # validates the item against the schema inside, or raises
        if kind == "item":
            items += 1
            assert len(found["era_tags"]) <= 20 and len(found["effects"]) <= 100 and len(found["flags"]) <= 18
        else:
            skipped += 1
    assert items > 10_000 and skipped < 20


@pytest.mark.skipif(not CACHE_READY, reason="needs the cached wiki pull (sources/eqlwiki/<date>, git-ignored) and derived/quests.json")
def test_the_whole_pull_builds_within_two_minutes_with_nothing_lost_or_timed_out(real_build):
    summary, out, seconds = real_build
    counts = summary["counts"]
    assert seconds < 120
    assert counts["items"] > 10_000
    assert set(counts["skipped"]) <= {"redirect", "no-itempage-template", "missing", "empty", "namespace", "empty-statsblock"}
    assert sum(counts["skipped"].values()) < 20
    assert set(counts["hidden_by_reason"]) <= HIDDEN_CODES
    assert counts["by_level"]["strict"] == 0  # no seen flags, no community reports, no allowed catalog
    assert min(counts["by_level"][level] for level in ("wiki", "disputed", "hidden")) > 100


@pytest.mark.skipif(not CACHE_READY, reason="needs the cached wiki pull (sources/eqlwiki/<date>, git-ignored) and derived/quests.json")
def test_the_number_of_wearables_with_a_live_drop_is_near_the_research_count(real_build):
    # The research counted 1,800 wearables with a drop in a zone the client flags; a sanity range, not a target.
    _, out, _ = real_build
    wiki_with_live_drop = 0
    for item in read_json(out / "catalog.json")["items"]:
        found = [reason["code"] for reason in item["evidence"]["reasons"]]
        kinds = ("live-source:quest", "live-source:vendor", "live-source:craft", "live-source:foraged")  # foraging is no drop
        drops = [c for c in found if c.startswith("live-source:") and c not in kinds]
        if item["slots"] and item["evidence"]["level"] == "wiki" and drops:
            wiki_with_live_drop += 1
    assert 1800 * 0.85 <= wiki_with_live_drop <= 1800 * 1.15, wiki_with_live_drop


@pytest.mark.skipif(not CACHE_READY, reason="needs the cached wiki pull (sources/eqlwiki/<date>, git-ignored) and derived/quests.json")
def test_a_sample_of_the_real_catalog_validates_and_the_known_items_are_graded_as_expected(real_build):
    import random

    _, out, _ = real_build
    document = read_json(out / "catalog.json")
    sample = random.Random(1).sample(document["items"], 300)
    validate_catalog({**document, "items": sorted(sample, key=lambda item: item["key"])})
    by_title = {item["wiki"]["title"]: item for item in document["items"]}
    assert level_and_codes(by_title["Engineer's Ring"])[0] == "wiki"
    assert level_and_codes(by_title["Mask of Deception"])[0] == "hidden"
    assert "removed-by-patch" in level_and_codes(by_title["Mask of Deception"])[1]
    assert level_and_codes(by_title["Obsidian Shard (Sky)"])[0] == "hidden"
    assert level_and_codes(by_title["Obsidian Shard"])[1] != ["removed-by-patch"]  # the namesake page is another item
    assert level_and_codes(by_title["Ogre Bouncer Shield"]) == ("hidden", ["cultural-container"])
    assert level_and_codes(by_title["Imbued Granite Spaulders"])[0] == "wiki"
    assert level_and_codes(by_title["A Cracked Femur"])[0] == "wiki"  # a Kunark tag, but it drops in an EQL-only zone
    assert level_and_codes(by_title["Darkwar Mask"])[0] == "disputed"


@pytest.mark.skipif(not CACHE_READY, reason="needs the cached wiki pull (sources/eqlwiki/<date>, git-ignored) and derived/quests.json")
def test_an_empty_race_list_comes_only_from_a_race_none_line_and_it_is_not_for_bis_with_the_race_none_note(real_build):
    # Read from the raw wikitext, not from the parser: no page states races that the parser loses.
    _, out, _ = real_build
    document = read_json(out / "catalog.json")
    pages = {f"w{page['pageid']}": page["content"] for page in read_wiki(CACHES[-1].parent).pages}
    race_line = re.compile(r"(?<![A-Za-z])race[ \t]*:[ \t]*([^\n<|]*)", re.IGNORECASE)  # a statsblock line may follow a <br>
    stated_none = no_line = 0
    for item in document["items"]:
        stated = race_line.findall(pages[item["key"]])
        if not stated:  # no Race line at all: all races, and no word about it
            no_line += 1
            assert item["races"] == ["ALL"] and "race NONE" not in json.dumps(item["evidence"]), item["key"]
            continue
        says_none = stated[0].strip().casefold() == "none"
        assert (item["races"] == []) == says_none, item["key"]  # [] is a stated NONE, and a stated NONE is []
        if says_none:
            stated_none += 1
            reasons = {reason["code"]: reason["text"] for reason in item["evidence"]["reasons"]}
            assert "race NONE" in reasons["not-for-bis"], item["key"]
    assert stated_none > 0 and no_line > 0
