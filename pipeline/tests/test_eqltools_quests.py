"""Tests for the quest reader: EQL Tools' quest JSON reduced to derived/quests.json.

The source files here are synthetic (invented quests, NPCs and zones); the committed derived file is
checked for its shape.
"""

import hashlib
import json
from pathlib import Path

import pytest

from trioforge.data.evidence import QuestTable
from trioforge.data.jsonio import load_strict
from trioforge.sources.eqltools_quests import ATTRIBUTION, main, read_quests, write_quests

REPO = Path(__file__).resolve().parents[2]


def raw_quest(n, **fields):
    quest = {
        "n": n,
        "t": n.replace(" ", "_"),
        "giver": "Old Zorb",
        "zone": "Zorblax Hollow",
        "era": "Classic Era",
        "rewards": ["Zorblax Blade"],
        "want": [["Quuxen Token", 1], ["Blarg Dust", 4]],
        "classes": [],
        "steps": [{"k": "give"}],
    }
    quest.update(fields)
    return quest


def source_file(tmp_path, quests, name="quest-items-2026-10-11.json", meta=None):
    path = tmp_path / name
    document = {"meta": {"license": "CC BY-SA 4.0", "source": "eqlwiki.com"} if meta is None else meta, "quests": quests}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def many(count=120):
    return [raw_quest(f"Zorblax Quest {n:03d}") for n in range(count)]


def test_a_quest_is_reduced_to_title_giver_zone_era_rewards_and_wants(tmp_path):
    path = source_file(tmp_path, [raw_quest("Zorblax Quest")], name="quests.json")
    (quest,) = read_quests(path, minimum=1)["quests"]
    assert quest == {
        "title": "Zorblax Quest",
        "wiki_title": None,  # the page title only differs by underscores
        "giver": "Old Zorb",
        "zone": "Zorblax Hollow",
        "era": "Classic Era",
        "rewards": ["Zorblax Blade"],
        "wants": ["Quuxen Token", "Blarg Dust"],
    }


def test_the_wiki_title_is_kept_when_it_names_the_page_differently(tmp_path):
    path = source_file(tmp_path, [raw_quest("Zorblax Quest", t="Quest_of_Zorblax")], name="q.json")
    assert read_quests(path, minimum=1)["quests"][0]["wiki_title"] == "Quest of Zorblax"


@pytest.mark.parametrize(
    "title,page",
    [
        ("Illusion: Zorblax Quest", "Illusion%3A_Zorblax_Quest"),
        ("Quest:Zorblax Spells", "Quest%3AZorblax_Spells"),
        ("Teir`Zorb Courier", "Teir%60Zorb_Courier"),
        ("Azzar's Dreadful Hat", "Azzar%27s_Dreadful_Hat"),
        ("Zorblax Words - X`Ta Part 1", "Zorblax_Words_-_X%60Ta_Part_1"),
        ("Zorblax Quest", "zorblax%20quest"),  # (the case is not a difference either)
    ],
)
def test_a_wiki_title_that_only_differs_by_percent_escapes_is_not_a_different_title(tmp_path, title, page):
    """The source writes the page title as a web address does (``%3A``, ``%60``, ``%27``): decoded, it is the quest's own title, so there is no other title to keep."""
    path = source_file(tmp_path, [raw_quest(title, t=page)], name="q.json")
    assert read_quests(path, minimum=1)["quests"][0]["wiki_title"] is None


def test_a_wiki_title_that_really_differs_is_kept_decoded(tmp_path):
    path = source_file(tmp_path, [raw_quest("Zorblax Quest", t="Quest%3AOf_Zorblax%27s_Quuxen"), raw_quest("Plain Quest", t="Plain%20Quest%20(2)")], name="q.json")
    titles = {quest["title"]: quest["wiki_title"] for quest in read_quests(path, minimum=1)["quests"]}
    assert titles == {"Zorblax Quest": "Quest:Of Zorblax's Quuxen", "Plain Quest": "Plain Quest (2)"}


def test_a_percent_sign_that_is_no_escape_is_left_as_it_is(tmp_path):
    path = source_file(tmp_path, [raw_quest("100 Percent Zorb", t="100%_Zorb_%ZZ")], name="q.json")
    assert read_quests(path, minimum=1)["quests"][0]["wiki_title"] == "100% Zorb %ZZ"


def test_a_quest_the_source_leaves_blank_stays_with_nulls(tmp_path):
    quest = raw_quest("Zorblax Quest", giver=None, zone=None, era=None, rewards=[], want=[])
    (found,) = read_quests(source_file(tmp_path, [quest], name="q.json"), minimum=1)["quests"]
    assert (found["giver"], found["zone"], found["era"], found["rewards"], found["wants"]) == (None, None, None, [], [])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("kunark Era", "Kunark Era"), ("Classic Era", "Classic Era"), ("FearHateRevamp Era", "Fearhaterevamp Era"), ("Unknown Era", "Unknown Era"),
     ("Classic", None), ("", None), (None, None), (7, None)],
)
def test_the_era_tag_is_written_as_the_page_parser_writes_it(tmp_path, raw, expected):
    path = source_file(tmp_path, [raw_quest("Zorblax Quest", era=raw)], name="q.json")
    assert read_quests(path, minimum=1)["quests"][0]["era"] == expected


def test_every_string_is_sanitized_because_the_source_is_wiki_text(tmp_path):
    hostile = raw_quest(
        "Quest<script>alert(1)</script>‮​ Name",
        giver="Evil <b>One</b>",
        zone="Zone\u0007 Name",
        rewards=["Blade<img src=x>", "", None, 5],
        want=[["Token‮", 1], "not a pair", [], [None, 2]],
    )
    (quest,) = read_quests(source_file(tmp_path, [hostile], name="q.json"), minimum=1)["quests"]
    assert quest["title"] == "Questscriptalert(1)/script Name"
    assert quest["giver"] == "Evil bOne/b"
    assert quest["zone"] == "Zone Name"
    assert quest["rewards"] == ["Bladeimg src=x"]
    assert quest["wants"] == ["Token"]
    flat = json.dumps(quest, ensure_ascii=False)
    for bad in ("<", ">", "‮", "​", "\u0007"):
        assert bad not in flat


def test_long_names_are_cut_to_two_hundred_characters_and_lists_are_capped(tmp_path):
    hostile = raw_quest("Z" * 500, rewards=[f"Reward {n}" for n in range(500)], want=[[f"Want {n}", 1] for n in range(500)])
    (quest,) = read_quests(source_file(tmp_path, [hostile], name="q.json"), minimum=1)["quests"]
    assert len(quest["title"]) == 200
    assert len(quest["rewards"]) == len(quest["wants"]) == 200


def test_repeated_names_in_a_list_are_kept_once_in_order(tmp_path):
    quest = raw_quest("Zorblax Quest", rewards=["B", "A", "B"], want=[["X", 1], ["X", 2], ["Y", 1]])
    (found,) = read_quests(source_file(tmp_path, [quest], name="q.json"), minimum=1)["quests"]
    assert found["rewards"] == ["B", "A"] and found["wants"] == ["X", "Y"]


def test_quests_without_a_title_are_skipped_and_counted(tmp_path):
    quests = [raw_quest("Zorblax Quest"), {"t": "No_Title"}, raw_quest("   "), "not a quest", None, raw_quest("Other Quest")]
    found = read_quests(source_file(tmp_path, quests, name="q.json"), minimum=1)
    assert [q["title"] for q in found["quests"]] == ["Other Quest", "Zorblax Quest"] and found["skipped"] == 4


def test_quests_are_sorted_by_title_ignoring_case(tmp_path):
    quests = [raw_quest("b quest"), raw_quest("A quest"), raw_quest("C quest")]
    found = read_quests(source_file(tmp_path, quests, name="q.json"), minimum=1)["quests"]
    assert [q["title"] for q in found] == ["A quest", "b quest", "C quest"]


@pytest.mark.parametrize("meta", [None, {}, {"license": "All rights reserved"}, {"license": "cc by-sa 4.0"}, "CC BY-SA 4.0"])
def test_a_file_that_does_not_declare_the_licence_is_refused(tmp_path, meta):
    path = tmp_path / "q.json"
    path.write_text(json.dumps({"meta": meta, "quests": many()}), encoding="utf-8")
    with pytest.raises(ValueError, match="licence"):
        read_quests(path)


def test_a_file_with_too_few_quests_is_refused(tmp_path):
    with pytest.raises(ValueError, match="fewer than"):
        read_quests(source_file(tmp_path, many(10)))
    assert len(read_quests(source_file(tmp_path, many(120)))["quests"]) == 120


@pytest.mark.parametrize("text", ["not json", '{"meta": {"license": "CC BY-SA 4.0"}, "meta": {}}', "[]", '{"meta": {"license": "CC BY-SA 4.0"}}'])
def test_a_file_that_is_not_the_expected_json_is_refused_without_echoing_it(tmp_path, text):
    path = tmp_path / "q.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        read_quests(path)
    assert text[:12] not in str(caught.value)


def test_the_document_has_provenance_licence_and_attribution(tmp_path):
    path = source_file(tmp_path, many(120))
    out = tmp_path / "derived" / "quests.json"
    document = write_quests(path, out, "2026-10-14", minimum=1)
    assert document["license"] == "CC BY-SA 4.0"
    assert document["attribution"] == ATTRIBUTION
    assert "EQL Tools" in ATTRIBUTION and "eqlwiki" in ATTRIBUTION
    provenance = document["provenance"]
    assert provenance["generated"] == "2026-10-14" and provenance["generator"].startswith("trioforge.sources.eqltools_quests ")
    assert provenance["inputs"] == [
        {
            "file": "sources/eqltools/quest-items-2026-10-11.json",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "date": "2026-10-11",
        }
    ]
    assert load_strict(out) == document


def test_the_output_is_one_quest_per_line_and_the_same_bytes_every_time(tmp_path):
    path = source_file(tmp_path, many(120))
    out = tmp_path / "quests.json"
    write_quests(path, out, "2026-10-14")
    first = out.read_bytes()
    write_quests(path, out, "2026-10-14")
    assert out.read_bytes() == first
    lines = first.decode("utf-8").split("\n")
    assert sum(1 for line in lines if line.startswith('  {"title"')) == 120
    assert first.endswith(b"}\n") and b"\r" not in first


def test_the_output_loads_as_a_quest_table(tmp_path):
    path = source_file(tmp_path, [raw_quest("Zorblax Quest", t="Quest_of_Zorblax"), *many(119)])
    out = tmp_path / "quests.json"
    write_quests(path, out, "2026-10-14")
    table = QuestTable.from_data(load_strict(out))
    assert table.by_title["zorblax quest"].giver == "Old Zorb"
    assert table.by_title["quest of zorblax"].title == "Zorblax Quest"
    assert table.by_reward["zorblax blade"] and table.consumed == {"quuxen token", "blarg dust"}


def test_a_failed_write_leaves_the_old_file_as_it_was(tmp_path):
    out = tmp_path / "quests.json"
    out.write_text("old", encoding="utf-8")
    with pytest.raises(ValueError):
        write_quests(source_file(tmp_path, many(3)), out, "2026-10-14")
    assert out.read_text(encoding="utf-8") == "old"


def test_the_command_line_writes_the_file_and_prints_counts(tmp_path, capsys):
    path = source_file(tmp_path, many(120))
    out = tmp_path / "out" / "quests.json"
    assert main(["--in", str(path), "--out", str(out), "--date", "2026-10-14"]) == 0
    assert "120 quests" in capsys.readouterr().out and out.is_file()


@pytest.mark.parametrize("case", ["missing", "bad-licence", "bad-date"])
def test_the_command_line_ends_with_exit_status_two_and_one_line(tmp_path, capsys, case):
    path = source_file(tmp_path, many(120), meta={"license": "proprietary"} if case == "bad-licence" else None)
    if case == "missing":
        path = tmp_path / "nothing.json"
    argv = ["--in", str(path), "--out", str(tmp_path / "quests.json")]
    if case == "bad-date":
        argv += ["--date", "2026-02-30"]
        with pytest.raises(SystemExit) as caught:
            main(argv)
        assert caught.value.code == 2
        return
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and err.count("\n") == 1
    assert not (tmp_path / "quests.json").exists()


# ---- the committed file ------------------------------------------------------------------------------


@pytest.mark.skipif(not (REPO / "derived" / "quests.json").is_file(), reason="derived/quests.json is not built")
def test_the_committed_quests_file_is_credited_and_loads():
    document = load_strict(REPO / "derived" / "quests.json")
    assert document["license"] == "CC BY-SA 4.0" and document["attribution"] == ATTRIBUTION
    assert len(document["quests"]) > 800
    table = QuestTable.from_data(document)
    assert len(table) > 800
    text = (REPO / "derived" / "quests.json").read_text(encoding="utf-8")
    assert "<" not in text and ">" not in text
    assert all(set(quest) == {"title", "wiki_title", "giver", "zone", "era", "rewards", "wants"} for quest in document["quests"])
