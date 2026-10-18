"""Tests for the results-diff report: what changed between two releases, and why.

The releases here are synthetic: the hand-written site fixture (invented names and numbers) twice, with one thing changed in the second at a time
(``release_helpers.py`` has the editors). The report classifies every changed scenario value, default pick, runner-up and item record by cause:

* ``code``: the hash of the model, solver and precompute code, or the solver options, differ;
* ``rule``: ``rules.json`` changed in a rule the pick uses (an Iksar rule does not touch an Ogre);
* ``data``: the catalog changed for an item that is in the old kit or in the new one;
* ``community``: the evidence of such an item changed by a community entry, added or retracted;
* ``new``: a trio or a tier the old release did not have.

When several apply all are listed, in that order of precedence. A change nothing explains is a solver diff: a bug, unless the value ties. The
Markdown shows the counts and the 20 largest changes of F; the JSON lists every change.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from release_helpers import (
    SHA_A,
    SHARDS,
    SLUG,
    ItemTable,
    ShardFile,
    add_invented_item,
    change_release_json,
    copy_trio,
    drop_community,
    drop_tier,
    edit,
    edit_runnerups,
    load,
    make_release,
    pair,
    remove_trio,
    rename_race,
    report_entry,
    retraction_entry,
    runnerup_place,
    set_community,
)
from test_evidence import ctx as ladder_context
from test_evidence import make_item as ladder_item

from trioforge.data.evidence import classify
from trioforge.precompute import assemble
from trioforge.reports import results_diff

OGR = ("OGR", "balanced", 4, "dw")  # a row of the fixture, and the kit it has (w90001 in the head, w80988 and w80113 in the hands)
HEAD_ITEM = "w90001"
OTHER_ITEM = "w80158"  # a sash the kit of OGR/balanced/+4/dw does not wear
NO_HEAD_ITEM = ("TRL", "balanced", 0, "dw")  # a row whose kit does not wear w90001


def shard(folder: Path, name: str = "wiki-own") -> ShardFile:
    return ShardFile(folder / SLUG / f"{name}.json")


def run(old: Path, new: Path):
    return results_diff.diff(old, new)


def of_kind(report, kind: str, **where):
    return [c for c in report.changes if c["kind"] == kind and all(c.get(k) == v for k, v in where.items())]


def nudge(folder: Path, delta: float = 5.0, *, name: str = "wiki-own", row=OGR) -> None:
    """Change the value of one scenario of the new release, and nothing it depends on."""
    file = shard(folder, name)
    target = file.row(*row)
    file.set_value(target, target[5] + delta)
    file.save()


def change_rule(folder: Path, rule: str, value="changed") -> None:
    document = assemble.read_release_json(folder)
    document["rules"][rule] = {"value": value, "status": "open"}
    assemble.write_release_json(folder, document)


def change_item(folder: Path, key: str = HEAD_ITEM) -> None:
    table = ItemTable(folder / "items.json")
    table.set_stats(key, AC=99)
    table.save()


def pick(folder: Path, key: str, delta: float = 4.0, *, name: str = "wiki-own") -> None:
    """Put an item in the head of the Ogre's kit in a shard (the wiki one, unless told otherwise), and the value that goes with it."""
    file = shard(folder, name)
    row = file.row(*OGR)
    file.set_place(row, "HEAD", key)
    file.set_value(row, row[5] + delta)
    file.save()


# ---- no change -------------------------------------------------------------------------------------------------------------------


def test_two_identical_releases_have_no_change(tmp_path):
    old, new = pair(tmp_path)
    report = run(old, new)
    assert report.changes == [] and report.summary["changes"] == 0 and report.summary["solver_diffs"] == 0
    assert "no change" in report.markdown().lower()
    assert json.loads(report.json_text())["changes"] == []


def test_a_release_is_read_from_its_tar_gz_as_from_its_folder(tmp_path):
    old, new = pair(tmp_path)
    nudge(new, 3.0)
    assets = {}
    for name, folder in (("old", old), ("new", new)):
        path = tmp_path / f"{name}.tar.gz"
        assemble.pack(folder, path)
        assets[name] = path
    from_folders, from_assets = run(old, new), run(assets["old"], assets["new"])
    assert from_assets.changes == from_folders.changes and from_assets.summary == from_folders.summary and len(from_assets.changes) == 1


def test_a_folder_that_is_no_release_is_refused(tmp_path):
    old, new = pair(tmp_path)
    (new / "release.json").unlink()
    with pytest.raises(assemble.ReleaseRefused, match=r"release\.json"):
        run(old, new)


# ---- the causes ----------------------------------------------------------------------------------------------------------------------


def test_a_value_that_changes_with_the_same_inputs_is_a_solver_diff_and_is_flagged_loudly(tmp_path):
    old, new = pair(tmp_path)
    nudge(new, 5.0)
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["view"] == {"evidence": "wiki", "buffs": "own", "race": "OGR", "role": "balanced", "tier": 4, "setup": "dw"}
    assert change["fields"] == ["F"] and change["causes"] == [] and change["primary"] is None and change["flag"] == "solver-diff"
    assert change["trio"] == SLUG and change["change"] == "changed" and change["delta"] == 5.0 and change["F"][1] - change["F"][0] == 5.0
    assert report.summary["solver_diffs"] == 1 and report.summary["by_cause"]["unexplained"] == 1
    text = report.markdown()
    assert "SOLVER DIFF" in text and "bug" in text.lower()
    assert text.index("SOLVER DIFF") < text.index("largest changes of F")  # before the table, not in a footnote


def test_a_different_kit_of_the_same_value_is_a_tie_and_no_bug(tmp_path):
    old, new = pair(tmp_path)
    file = shard(new)
    file.set_place(file.row(*OGR), "HEAD", OTHER_ITEM)
    file.save()
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["fields"] == ["kit"] and change["flag"] == "tie" and change["causes"] == []
    assert change["kit"] == [{"place": "HEAD", "old": HEAD_ITEM, "new": OTHER_ITEM}]
    assert report.summary["ties"] == 1 and report.summary["solver_diffs"] == 0
    assert "SOLVER DIFF" not in report.markdown()


def test_a_different_kit_of_another_value_with_the_same_inputs_is_a_solver_diff(tmp_path):
    old, new = pair(tmp_path)
    pick(new, OTHER_ITEM, -2.0)
    (change,) = of_kind(run(old, new), "scenario")
    assert change["fields"] == ["F", "kit"] and change["flag"] == "solver-diff" and change["causes"] == []


def test_a_rule_the_pick_uses_is_the_cause_of_a_change(tmp_path):
    old, new = pair(tmp_path)
    change_rule(new, "monk.weight_curve")
    nudge(new)  # the trio has a Monk, so the Monk curve is in every pick
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["causes"] == ["rule"] and change["primary"] == "rule" and change["flag"] is None
    assert report.summary["solver_diffs"] == 0 and report.summary["by_cause"]["rule"] == 1
    assert report.summary["inputs"]["rules"] == ["monk.weight_curve"]


def test_a_rule_the_pick_does_not_use_is_no_cause(tmp_path):
    """An Iksar rule changed and an Ogre's pick moved: the rule is not why, so it is a solver diff."""
    old, new = pair(tmp_path)
    change_rule(new, "race.iksar_ac_bonus", 40)
    nudge(new)
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == [] and change["flag"] == "solver-diff"


@pytest.mark.parametrize(
    ("rule", "row", "applies"),
    [
        ("race.iksar_ac_bonus", ("TRL", "balanced", 4, "dw"), False),
        ("monk.weight_curve", ("TRL", "balanced", 4, "dw"), True),  # the trio has a Monk
        ("weapons.dual_wield_factor", ("TRL", "balanced", 4, "dw"), True),
        ("weapons.dual_wield_factor", ("TRL", "balanced", 4, "2h"), False),  # only the dual-wield setup counts the off hand
        ("tier.stat_rule", ("TRL", "balanced", 4, "dw"), True),
        ("tier.stat_rule", ("TRL", "balanced", 0, "dw"), False),  # at +0 no tier rule is in a pick
        ("haste.cap_pct", ("TRL", "balanced", 4, "dw"), False),  # a trio with a Monk has the other cap
        ("buffs.max_slots", ("TRL", "balanced", 0, "dw"), True),  # a rule with no scope is in every pick
    ],
)
def test_each_rule_is_in_the_picks_it_is_about(tmp_path, rule, row, applies):
    old, new = pair(tmp_path)
    change_rule(new, rule)
    nudge(new, 2.0, row=row)
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == (["rule"] if applies else [])


def test_the_iksar_rules_are_in_the_picks_of_an_iksar(tmp_path):
    old, new = pair(tmp_path)
    for folder in (old, new):  # (the fixture has no Iksar: the Ogre row is called one in both)
        rename_race(folder, "wiki-own", OGR, "IKS")
    change_rule(new, "race.iksar_ac_bonus", 40)
    nudge(new, row=("IKS", "balanced", 4, "dw"))
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == ["rule"] and change["view"]["race"] == "IKS"


def test_a_changed_record_of_an_item_in_the_kit_is_a_data_cause(tmp_path):
    old, new = pair(tmp_path)
    change_item(new)
    nudge(new)
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["causes"] == ["data"] and change["primary"] == "data" and change["flag"] is None and HEAD_ITEM in change["items"]
    (record,) = of_kind(report, "item", key=HEAD_ITEM)
    assert record["causes"] == ["data"] and record["change"] == "changed" and record["fields"] == ["stats"]


def test_a_changed_record_of_an_item_that_is_in_no_kit_is_no_cause_of_a_change_in_a_pick(tmp_path):
    old, new = pair(tmp_path)
    change_item(new, OTHER_ITEM)
    nudge(new)
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["causes"] == [] and change["flag"] == "solver-diff"
    assert [r["key"] for r in of_kind(report, "item")] == [OTHER_ITEM]  # (the record itself is listed: it did change)


def test_the_new_kit_counts_as_well_as_the_old_one(tmp_path):
    old, new = pair(tmp_path)
    change_item(new, OTHER_ITEM)  # the item the new kit wears, and the old one did not
    pick(new, OTHER_ITEM, 3.0)
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == ["data"] and set(change["items"]) >= {HEAD_ITEM, OTHER_ITEM}


def test_a_new_game_patch_is_a_data_cause_of_every_change(tmp_path):
    old, new = pair(tmp_path)
    change_release_json(new, game_patch="2026-10-12")
    nudge(new)
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["causes"] == ["data"]
    assert report.summary["inputs"]["game_patch"] == ["2026-09-22", "2026-10-12"]


def test_a_new_code_hash_is_a_code_cause_and_comes_first(tmp_path):
    old, new = pair(tmp_path)
    change_release_json(new, code_hash="9f" * 32)
    change_rule(new, "monk.weight_curve")
    change_item(new)
    nudge(new)
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["causes"] == ["code", "rule", "data"] and change["primary"] == "code" and change["flag"] is None
    assert report.summary["inputs"]["code"] is True and report.summary["solver_diffs"] == 0


def test_other_solver_options_are_a_code_cause_too(tmp_path):
    old, new = pair(tmp_path)
    change_release_json(new, solver={"canonical": True, "mip_rel_gap": 0.01, "highs": "1.15.1"})
    nudge(new)
    assert of_kind(run(old, new), "scenario")[0]["causes"] == ["code"]
    old, new = pair(tmp_path / "again")
    change_release_json(new, build_options={"any_rule": "none", "haste_assumed": None})
    nudge(new)
    assert of_kind(run(old, new), "scenario")[0]["causes"] == ["code"]


# ---- community evidence --------------------------------------------------------------------------------------------------------------


def test_a_pick_that_rests_on_a_new_community_entry_is_community_only(tmp_path):
    old, new = pair(tmp_path)
    add_invented_item(old, "w91001", strict=False)
    add_invented_item(new, "w91001", strict=True)
    set_community(new, reports=[report_entry("w91001", 5)])  # (the entry that the codes of the record rest on: release.json lists it)
    pick(new, "w91001", name="strict-own")  # (a strict pick: the strict pool is the one the entry changes)
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["causes"] == ["community"] and change["primary"] == "community" and change["flag"] is None
    assert report.summary["community_only"] == 2 and report.summary["by_cause"]["community"] == 3  # the pick, the default pick made from it, and the record of the item
    assert listed(report, "added") == [("w91001", 5)] and listed(report, "retracted") == [] and report.summary["retractions"] == 0
    (record,) = of_kind(report, "item", key="w91001")
    assert record["community"] == "added" and record["evidence"] == ["wiki", "strict"] and record["causes"] == ["community"]


def test_a_retraction_is_listed_and_is_the_cause_of_the_pick_that_goes(tmp_path):
    """A community entry removed: the item falls from strict to wiki, and the pick that rested on it moves."""
    old, new = pair(tmp_path)
    add_invented_item(old, "w91001", strict=True)
    add_invented_item(new, "w91001", strict=False)
    set_community(old, reports=[report_entry("w91001", 5)])
    set_community(new, retracted=[retraction_entry("w91001", 5)])  # (the entry moved to the retractions: release.json lists it)
    pick(old, "w91001", name="strict-own")
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    head = shard(new, "strict-own").kit(shard(new, "strict-own").row(*OGR))[0]  # (the head the strict kit has when it does not wear the retracted item)
    assert change["causes"] == ["community"] and change["kit"] == [{"place": "HEAD", "old": "w91001", "new": head}]
    assert report.summary["retractions"] == 1 and listed(report, "retracted") == [("w91001", 5)] and listed(report, "added") == []
    (record,) = of_kind(report, "item", key="w91001")
    assert record["community"] == "removed" and record["evidence"] == ["strict", "wiki"]
    text = report.markdown()
    assert "retract" in text.lower() and "w91001" in text


def test_a_community_entry_for_an_item_that_was_already_strict_changes_no_pick(tmp_path):
    old, new = pair(tmp_path)
    table = ItemTable(new / "items.json")
    table.set_evidence(HEAD_ITEM, "strict", ["community-report"])  # (it was strict already: the level did not move)
    table.save()
    nudge(new)
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["causes"] == [] and change["flag"] == "solver-diff"  # the entry is no reason for a different value
    assert of_kind(report, "item", key=HEAD_ITEM)[0]["community"] == "added"


def test_an_evidence_level_that_moves_without_a_community_entry_is_data(tmp_path):
    old, new = pair(tmp_path)
    add_invented_item(old, "w91001", strict=False)
    add_invented_item(new, "w91001", strict=False)
    table = ItemTable(new / "items.json")
    table.set_evidence("w91001", "strict")  # strict, and nothing public says why
    table.save()
    pick(new, "w91001", name="strict-own")
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == ["data"]


def test_all_the_causes_that_apply_are_listed_in_the_order_of_precedence(tmp_path):
    old, new = pair(tmp_path)
    change_rule(new, "monk.weight_curve")
    add_invented_item(old, "w91001", strict=False)
    add_invented_item(new, "w91001", strict=True, AC=77)  # the new item changed its stats as well as its evidence
    pick(new, "w91001", name="strict-own")
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == ["rule", "data", "community"] and change["primary"] == "rule"
    change_release_json(new, code_hash="9f" * 32)
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == ["code", "rule", "data", "community"]


# ---- community entries as the ladder writes them -----------------------------------------------------------------------------------------------
#
# The item table of a release holds, for each item, the evidence level and the reason codes of the catalog (the codes of the live sources left out). The tests below do not write
# those codes by hand: they ask the ladder what it gives an invented item with and without a report (``rules/community-seen.json``), with and without the wiki's own mark that
# the item is gone, or a zone that is closed, and put that in the item table of each release. The entries of the list themselves are what ``release.json`` records
# (``community``): the report lists what was added and retracted from them, by item and issue, and what the codes of an item do from its record.

LADDER_ITEM = "w91001"
GONE_MARKS = ["wiki_banner_delete", "removed_note"]  # the banner of a deleted page, and the note that the item was removed from the game
LIVE = "Plane of Hate"  # a zone the client flags and the developers have opened
CLOSED = "Rujarkian Hills"  # a zone the client flags and the developers say is not open yet
UNFLAGGED = "Kael Drakkal"  # a zone the client does not flag


def ladder_evidence(flags: list[str], *, reported: bool, zone: str = LIVE, name: str = "Invented Community Cap 91001") -> tuple[str, list[str]]:
    item = ladder_item(LADDER_ITEM, name, drops=[(zone, ["Innoruuk"])], era_tags=["Classic Era"], flags=flags)
    result = classify(item, ladder_context(community_keys={LADDER_ITEM} if reported else set()))
    return result["level"], sorted({reason["code"].split(":")[0] for reason in result["reasons"]} - {"live-source"})


def put_ladder_evidence(
    folder: Path, flags: list[str], *, reported: bool, retracted: bool = False, zone: str = LIVE, issue: int = 5, name: str = "Invented Community Cap 91001"
) -> None:
    """The item table of a release as the ladder writes it for the invented item, and the entries that ``release.json`` records beside it: the report while it stands in the
    file (``reported``), the retraction when it was taken back (``retracted``)."""
    add_invented_item(folder, LADDER_ITEM, strict=False)
    table = ItemTable(folder / "items.json")
    table.set_evidence(LADDER_ITEM, *ladder_evidence(flags, reported=reported, zone=zone, name=name))
    table.save()
    set_community(
        folder,
        reports=[report_entry(LADDER_ITEM, issue)] if reported else [],
        retracted=[retraction_entry(LADDER_ITEM, issue)] if retracted else [],
    )


def listed(report, name: str) -> list[tuple[str, int]]:
    """The ``(key, issue)`` of the entries that the report lists under one of the lists of ``summary["community"]``."""
    return [(entry["key"], entry["issue"]) for entry in report.summary["community"][name]]


def test_what_the_ladder_writes_for_a_report_is_what_these_tests_start_from():
    assert ladder_evidence([], reported=True) == ("strict", ["community-report"])
    assert ladder_evidence([], reported=False) == ("wiki", [])
    assert ladder_evidence(["wiki_banner_delete"], reported=True) == ("hidden", ["community-report-outweighed", "wiki-marked-not-in-eql"])
    assert ladder_evidence(["removed_note"], reported=False) == ("hidden", ["wiki-marked-removed"])
    assert ladder_evidence([], reported=True, zone=CLOSED) == ("hidden", ["community-report-outweighed", "zone-unreleased"])
    assert ladder_evidence([], reported=False, zone=CLOSED) == ("hidden", ["zone-unreleased"])


# -- the retraction of a report, and the report of an item the wiki marks as gone


def test_the_retraction_of_a_report_on_a_live_item_is_listed_in_the_report_of_the_next_release(tmp_path):
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [], reported=True)
    put_ladder_evidence(new, [], reported=False, retracted=True)
    report = run(old, new)
    assert listed(report, "retracted") == [(LADDER_ITEM, 5)] and listed(report, "added") == [] and report.summary["retractions"] == 1
    assert report.summary["community"]["retracted"] == [{"key": LADDER_ITEM, "issue": 5, "reason": "withdrawn"}]
    assert report.summary["community"]["strict_lost"] == [{"key": LADDER_ITEM, "why": "retracted", "by": []}] and report.summary["community"]["strict_gained"] == []
    (record,) = of_kind(report, "item", key=LADDER_ITEM)
    assert record["community"] == "removed" and record["evidence"] == ["strict", "wiki"] and record["causes"] == ["community"]
    text = report.markdown()
    assert f"- retracted (1): `{LADDER_ITEM}` (issue 5, withdrawn)" in text and f"- no longer strict, the report retracted (1): `{LADDER_ITEM}`" in text


@pytest.mark.parametrize("flag", GONE_MARKS)
def test_the_retraction_of_a_report_the_wikis_mark_outweighed_is_listed_too_and_moves_no_level(tmp_path, flag):
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [flag], reported=True)
    put_ladder_evidence(new, [flag], reported=False, retracted=True)
    report = run(old, new)
    assert listed(report, "retracted") == [(LADDER_ITEM, 5)] and report.summary["retractions"] == 1
    assert report.summary["community"]["strict_lost"] == [] and report.summary["community"]["strict_gained"] == []  # (hidden before and after)
    (record,) = of_kind(report, "item", key=LADDER_ITEM)
    assert record["community"] == "removed" and record["evidence"] is None and record["causes"] == ["community"]
    assert f"- retracted (1): `{LADDER_ITEM}` (issue 5, withdrawn)" in report.markdown()
    assert of_kind(report, "scenario") == [] and report.summary["solver_diffs"] == 0 and report.summary["community_only"] == 0  # (no pick rested on it)


@pytest.mark.parametrize("flag", GONE_MARKS)
def test_a_report_on_a_marked_item_is_listed_as_added_and_changes_no_level(tmp_path, flag):
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [flag], reported=False)
    put_ladder_evidence(new, [flag], reported=True)
    report = run(old, new)
    assert listed(report, "added") == [(LADDER_ITEM, 5)] and listed(report, "retracted") == [] and report.summary["retractions"] == 0
    (record,) = of_kind(report, "item", key=LADDER_ITEM)
    assert record["community"] == "added" and record["evidence"] is None and record["causes"] == ["community"]


def test_a_mark_of_the_wiki_that_outweighs_a_report_which_made_the_item_strict_is_data_and_no_retraction(tmp_path):
    """The report stands in the file: what moved the item from strict to hidden is the wiki, and the report is not retracted. It is said all the same that the item is no longer
    strict, and why: the report is outweighed, by the mark."""
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [], reported=True)
    put_ladder_evidence(new, ["wiki_banner_dne"], reported=True)
    report = run(old, new)
    (record,) = of_kind(report, "item", key=LADDER_ITEM)
    assert record["community"] is None and record["evidence"] == ["strict", "hidden"] and record["causes"] == ["data"]
    assert listed(report, "added") == [] and listed(report, "retracted") == [] and report.summary["retractions"] == 0
    assert report.summary["community"]["strict_lost"] == [{"key": LADDER_ITEM, "why": "outweighed", "by": ["wiki-marked-not-in-eql"]}]
    assert report.summary["community"]["strict_gained"] == []


# -- a report that stood outweighed and counts now: the wiki's edit let it through, and the community is a cause too


LIFTS = [
    pytest.param(["wiki_banner_dne"], LIVE, id="the banner that says the item does not exist is taken off the page"),
    pytest.param(["removed_note"], LIVE, id="the note that the item was removed from the game is taken off the page"),
    pytest.param(["wiki_banner_delete", "removed_note"], LIVE, id="both marks are taken off the page"),
    pytest.param([], CLOSED, id="the zone is opened"),
    pytest.param([], UNFLAGGED, id="the client flags the zone"),
]


@pytest.mark.parametrize(("flags", "zone"), LIFTS)
def test_a_report_that_stood_outweighed_and_counts_now_is_a_community_cause_beside_the_data(tmp_path, flags, zone):
    """One report must not reach the kits through a later edit of the wiki without the report saying so: the item goes from hidden to strict, the wiki's edit is a cause, and
    the report is a cause that is listed under Community evidence (it was in the file already: it is not an entry added)."""
    old, new = pair(tmp_path)
    put_ladder_evidence(old, flags, reported=True, zone=zone)
    put_ladder_evidence(new, [], reported=True)
    assert ladder_evidence(flags, reported=True, zone=zone)[0] == "hidden" and ladder_evidence([], reported=True)[0] == "strict"
    report = run(old, new)
    (record,) = of_kind(report, "item", key=LADDER_ITEM)
    assert record["community"] == "lifted" and record["evidence"] == ["hidden", "strict"] and record["causes"] == ["data", "community"]
    assert record["fields"] == ["evidence"]  # (the premise of R1: nothing but the evidence of the record changes, and the reason that went away is in its codes)
    assert report.summary["community"]["strict_gained"] == [LADDER_ITEM] and report.summary["community"]["strict_lost"] == []
    assert listed(report, "added") == [] and listed(report, "retracted") == [] and report.summary["retractions"] == 0
    assert f"- strict now because of a report (1): `{LADDER_ITEM}`" in report.markdown()


@pytest.mark.parametrize(("flags", "zone"), LIFTS)
def test_a_pick_that_wears_an_item_a_report_lifted_names_the_community_and_the_data(tmp_path, flags, zone):
    old, new = pair(tmp_path)
    put_ladder_evidence(old, flags, reported=True, zone=zone)
    put_ladder_evidence(new, [], reported=True)
    pick(new, LADDER_ITEM, name="strict-own")  # (a strict pick: the strict pool is the one the lift changes)
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["causes"] == ["data", "community"] and change["primary"] == "data" and change["flag"] is None
    assert report.summary["community_only"] == 0  # (the wiki's edit is a cause as well: it is not the community alone)


def test_an_item_that_the_maintainer_alone_has_seen_is_no_lift(tmp_path):
    """The item table's level has the private flags merged and its codes are the public catalog's: a level that moves with no community code to show for it is the data's."""
    old, new = pair(tmp_path)
    put_ladder_evidence(old, ["wiki_banner_dne"], reported=True)
    put_ladder_evidence(new, ["wiki_banner_dne"], reported=True)
    table = ItemTable(new / "items.json")
    table.set_evidence(LADDER_ITEM, "strict", ["community-report-outweighed", "wiki-marked-not-in-eql"])  # (the level has the private flag merged; the codes stay the catalog's)
    table.save()
    (record,) = of_kind(run(old, new), "item", key=LADDER_ITEM)
    assert record["community"] is None and record["causes"] == ["data"]


# -- an item that stops being strict: the report is retracted, or it is outweighed (and by what)


def lost(report) -> list[dict]:
    return report.summary["community"]["strict_lost"]


OUTWEIGHERS = [
    pytest.param(["wiki_banner_dne"], LIVE, ["wiki-marked-not-in-eql"], id="the banner that says the item does not exist"),
    pytest.param(["wiki_banner_delete"], LIVE, ["wiki-marked-not-in-eql"], id="the banner of a deleted page"),
    pytest.param(["removed_note"], LIVE, ["wiki-marked-removed"], id="the note that the item was removed from the game"),
    pytest.param(["wiki_banner_delete", "removed_note"], LIVE, ["wiki-marked-not-in-eql", "wiki-marked-removed"], id="both marks"),
    pytest.param([], CLOSED, ["zone-unreleased"], id="the zone is not open yet"),
    pytest.param([], UNFLAGGED, ["zones-not-in-eql"], id="the client does not flag the zone"),
]


@pytest.mark.parametrize(("flags", "zone", "by"), OUTWEIGHERS)
def test_an_item_that_stops_being_strict_because_its_report_is_outweighed_is_listed_with_what_outweighs_it(tmp_path, flags, zone, by):
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [], reported=True)
    put_ladder_evidence(new, flags, reported=True, zone=zone)
    report = run(old, new)
    assert lost(report) == [{"key": LADDER_ITEM, "why": "outweighed", "by": by}] and report.summary["community"]["strict_gained"] == []
    (record,) = of_kind(report, "item", key=LADDER_ITEM)
    assert record["community"] is None and record["causes"] == ["data"]  # (the entry did not change: the wiki or the client data did)
    assert listed(report, "retracted") == [] and report.summary["retractions"] == 0
    text = report.markdown()
    assert f"- no longer strict, the report outweighed (1): `{LADDER_ITEM}` (by {', '.join(by)})" in text and "the report retracted" not in text


@pytest.mark.parametrize(("name", "code"), [("Mask of Zorblax", "removed-by-patch"), ("Wind Zorblax Helm", "removed-by-research")])
def test_an_item_that_a_patch_or_research_removes_while_its_report_stands_is_listed_as_outweighed_by_the_removal(tmp_path, name, code):
    """The ladder hides such an item whatever players say and leaves no trace of the report in its codes; the file still has it."""
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [], reported=True)
    put_ladder_evidence(new, [], reported=True, name=name)
    assert ladder_evidence([], reported=True, name=name) == ("hidden", [code])
    report = run(old, new)
    assert lost(report) == [{"key": LADDER_ITEM, "why": "outweighed", "by": [code]}]
    assert listed(report, "retracted") == [] and f"(by {code})" in report.markdown() and "the report retracted" not in report.markdown()


def test_an_item_whose_report_is_retracted_at_the_same_time_as_a_removal_or_a_mark_is_listed_as_retracted(tmp_path):
    for number, (flags, name) in enumerate(((["wiki_banner_dne"], "Invented Community Cap 91001"), ([], "Mask of Zorblax"))):
        old, new = pair(tmp_path / str(number))
        put_ladder_evidence(old, [], reported=True)
        put_ladder_evidence(new, flags, reported=False, retracted=True, name=name)  # (no report stands: nothing is outweighed)
        report = run(old, new)
        assert lost(report) == [{"key": LADDER_ITEM, "why": "retracted", "by": []}], (flags, name)
        assert listed(report, "retracted") == [(LADDER_ITEM, 5)] and f"- no longer strict, the report retracted (1): `{LADDER_ITEM}`" in report.markdown()


def test_an_item_a_patch_removes_is_taken_to_outweigh_its_report_when_the_new_release_lists_no_entries(tmp_path):
    """Whether the report still stands cannot be told from a release that does not list its entries: the removal is taken to outweigh it."""
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [], reported=True)
    put_ladder_evidence(new, [], reported=True, name="Mask of Zorblax")
    drop_community(new)
    assert lost(run(old, new)) == [{"key": LADDER_ITEM, "why": "outweighed", "by": ["removed-by-patch"]}]


def test_the_markdown_says_each_way_an_item_stopped_being_strict_on_a_line_of_its_own(tmp_path):
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [], reported=True)
    put_ladder_evidence(new, ["wiki_banner_dne", "removed_note"], reported=True)
    other = "w91002"
    for folder in (old, new):
        add_invented_item(folder, other, strict=True)
    table = ItemTable(new / "items.json")
    table.set_evidence(other, "wiki", [])
    table.save()
    set_community(old, reports=[report_entry(LADDER_ITEM, 5), report_entry(other, 6)])
    set_community(new, reports=[report_entry(LADDER_ITEM, 5)], retracted=[retraction_entry(other, 6, reason="rejected")])
    report = run(old, new)
    assert lost(report) == [
        {"key": LADDER_ITEM, "why": "outweighed", "by": ["wiki-marked-not-in-eql", "wiki-marked-removed"]},
        {"key": other, "why": "retracted", "by": []},
    ]
    text = report.markdown()
    assert f"- no longer strict, the report retracted (1): `{other}`" in text
    assert f"- no longer strict, the report outweighed (1): `{LADDER_ITEM}` (by wiki-marked-not-in-eql, wiki-marked-removed)" in text


# -- a record that is new in the second release, and strict by a report that the first release recorded already


def test_a_record_that_is_new_in_the_second_release_and_strict_by_a_report_already_recorded_is_counted(tmp_path):
    """The report is in the file of both releases; the catalog of the first had no page for the item. The item is strict now because of the report, and the report says so."""
    old, new = pair(tmp_path)
    set_community(old, reports=[report_entry(LADDER_ITEM, 5)])
    put_ladder_evidence(new, [], reported=True)  # (the record is in the second release only)
    report = run(old, new)
    (record,) = of_kind(report, "item", key=LADDER_ITEM)
    assert record["change"] == "added" and record["community"] == "added" and record["evidence"] == [None, "strict"] and record["causes"] == ["data", "community"]
    assert report.summary["community"]["strict_gained"] == [LADDER_ITEM] and report.summary["community"]["strict_lost"] == []
    assert listed(report, "added") == [] and listed(report, "retracted") == []  # (the entry is no new entry: the first release recorded it)
    assert f"- strict now because of a report (1): `{LADDER_ITEM}`" in report.markdown()


def test_a_pick_that_wears_a_record_new_and_strict_by_a_report_names_the_data_and_the_community(tmp_path):
    old, new = pair(tmp_path)
    set_community(old, reports=[report_entry(LADDER_ITEM, 5)])
    put_ladder_evidence(new, [], reported=True)
    pick(new, LADDER_ITEM, name="strict-own")
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == ["data", "community"] and change["flag"] is None


@pytest.mark.parametrize("flags", [["wiki_banner_dne"], ["removed_note"]])
def test_a_record_new_in_the_second_release_whose_report_the_wiki_outweighs_is_not_counted_as_strict(tmp_path, flags):
    old, new = pair(tmp_path)
    set_community(old, reports=[report_entry(LADDER_ITEM, 5)])
    put_ladder_evidence(new, flags, reported=True)
    report = run(old, new)
    (record,) = of_kind(report, "item", key=LADDER_ITEM)
    assert record["change"] == "added" and record["community"] == "added" and record["evidence"] == [None, "hidden"]
    assert report.summary["community"]["strict_gained"] == []


def test_a_record_new_in_the_second_release_with_no_report_is_the_datas_alone(tmp_path):
    old, new = pair(tmp_path)
    put_ladder_evidence(new, [], reported=False)
    (record,) = of_kind(run(old, new), "item", key=LADDER_ITEM)
    assert record["community"] is None and record["causes"] == ["data"]


# -- what the report publishes does not depend on the private flags


@pytest.mark.parametrize(
    ("name", "old_flags", "old_reported", "new_flags", "new_reported", "new_retracted", "old_zone"),
    [
        pytest.param("a report is retracted", [], True, [], False, True, LIVE, id="a report is retracted"),
        pytest.param("a report is added", [], False, [], True, False, LIVE, id="a report is added"),
        pytest.param("a mark goes", ["wiki_banner_dne"], True, [], True, False, LIVE, id="the mark that outweighed a report goes"),
        pytest.param("a zone opens", [], True, [], True, False, CLOSED, id="the zone that outweighed a report opens"),
        pytest.param("a mark comes", [], True, ["wiki_banner_dne"], True, False, LIVE, id="a mark outweighs a report that stands"),
    ],
)
def test_the_markdown_and_the_lists_of_the_report_are_the_same_whether_or_not_the_maintainer_has_seen_the_item(
    tmp_path, name, old_flags, old_reported, new_flags, new_reported, new_retracted, old_zone
):
    """The item table has the private flags merged into its levels and the codes of the public catalog beside them. What the committed Markdown says about the items that a report
    made strict or stopped making strict must come from the codes: if it came from the levels, an item the maintainer has seen would be missing from it (its level does not move),
    and the gap would tell which items they have seen."""

    def releases(seen: bool):
        folder = tmp_path / ("seen" if seen else "unseen")
        old, new = pair(folder)
        put_ladder_evidence(old, old_flags, reported=old_reported, zone=old_zone)
        put_ladder_evidence(new, new_flags, reported=new_reported, retracted=new_retracted)
        if seen:  # the flag is merged into the level of every release; the codes stay the public catalog's
            for release_folder in (old, new):
                table = ItemTable(release_folder / "items.json")
                record = table.record(LADDER_ITEM)
                table.set_evidence(LADDER_ITEM, "strict", record["evidence"].get("codes", ()))
                table.save()
        return old, new

    unseen, seen = (run(*releases(flag)) for flag in (False, True))
    assert seen.summary["community"] == unseen.summary["community"] and seen.summary["retractions"] == unseen.summary["retractions"]
    assert seen.markdown() == unseen.markdown(), name


# -- the entries themselves, from release.json


def test_a_duplicate_retracted_while_another_report_of_the_item_stands_is_listed(tmp_path):
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [], reported=True, issue=6)
    put_ladder_evidence(new, [], reported=True, issue=6)  # (the item is strict by issue 6 in both: its record does not move)
    set_community(old, reports=[report_entry(LADDER_ITEM, 5), report_entry(LADDER_ITEM, 6)])
    set_community(new, reports=[report_entry(LADDER_ITEM, 6)], retracted=[retraction_entry(LADDER_ITEM, 5, reason="duplicate")])
    report = run(old, new)
    assert of_kind(report, "item") == [] and report.summary["changes"] == 0
    assert report.summary["community"]["retracted"] == [{"key": LADDER_ITEM, "issue": 5, "reason": "duplicate"}] and report.summary["retractions"] == 1
    assert f"- retracted (1): `{LADDER_ITEM}` (issue 5, duplicate)" in report.markdown()


def test_a_second_report_of_an_item_that_is_already_reported_is_listed_as_added(tmp_path):
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [], reported=True, issue=5)
    put_ladder_evidence(new, [], reported=True, issue=5)
    set_community(new, reports=[report_entry(LADDER_ITEM, 5), report_entry(LADDER_ITEM, 6, kind="tier")])
    report = run(old, new)
    assert of_kind(report, "item") == [] and report.summary["changes"] == 0
    assert report.summary["community"]["added"] == [{"key": LADDER_ITEM, "issue": 6}]
    assert f"- added (1): `{LADDER_ITEM}` (issue 6)" in report.markdown()


def test_an_entry_on_an_item_that_a_patch_or_research_removed_is_listed_though_nothing_else_moves(tmp_path):
    """The ladder hides such an item whatever players say, so the codes are the removal's alone before the report, with it and after its retraction: only the entries tell."""
    old = make_release(tmp_path / "old", tag="data-2026-10-10")
    new = make_release(tmp_path / "new", tag="data-2026-10-17")
    later = make_release(tmp_path / "later", tag="data-2026-10-24")
    for folder in (old, new, later):
        add_invented_item(folder, LADDER_ITEM, strict=False)
        table = ItemTable(folder / "items.json")
        table.set_evidence(LADDER_ITEM, "hidden", ["removed-by-patch"])
        table.save()
    set_community(new, reports=[report_entry(LADDER_ITEM, 5)])
    set_community(later, retracted=[retraction_entry(LADDER_ITEM, 5, reason="wrong-item")])
    added, retracted = run(old, new), run(new, later)
    assert of_kind(added, "item") == [] and added.summary["community"]["added"] == [{"key": LADDER_ITEM, "issue": 5}]
    assert of_kind(retracted, "item") == [] and retracted.summary["community"]["retracted"] == [{"key": LADDER_ITEM, "issue": 5, "reason": "wrong-item"}]
    assert retracted.summary["retractions"] == 1


def test_the_entries_are_compared_by_item_and_issue_and_not_by_where_they_stand_or_how_many_there_are(tmp_path):
    old, new = pair(tmp_path)
    one, two = report_entry("w91001", 5), report_entry("w91002", 6)
    set_community(old, reports=[one, two])
    set_community(new, reports=[two, one])  # (the same entries in another order)
    assert run(old, new).summary["community"] == {
        "added": [], "retracted": [], "deleted": [], "changed": [], "first": {"reports": [], "retracted": []}, "strict_gained": [], "strict_lost": [], "note": None,
    }  # fmt: skip


def test_an_entry_changed_in_place_is_listed_with_the_fields_that_differ(tmp_path):
    old, new = pair(tmp_path)
    set_community(old, reports=[report_entry("w91001", 5)], retracted=[retraction_entry("w91002", 6, reason="duplicate")])
    set_community(new, reports=[report_entry("w91001", 5, kind="tier", date="2026-10-16")], retracted=[retraction_entry("w91002", 6, reason="rejected")])
    changed = run(old, new).summary["community"]["changed"]
    assert changed == [
        {"key": "w91001", "issue": 5, "list": "reports", "fields": ["kind", "date"]},
        {"key": "w91002", "issue": 6, "list": "retracted", "fields": ["reason"]},
    ]


def test_an_entry_that_leaves_the_file_with_no_retraction_is_listed_as_deleted(tmp_path):
    old, new = pair(tmp_path)
    set_community(old, reports=[report_entry("w91001", 5)], retracted=[retraction_entry("w91002", 6)])
    report = run(old, new)
    assert report.summary["community"]["deleted"] == [{"key": "w91001", "issue": 5, "was": "report"}, {"key": "w91002", "issue": 6, "was": "retraction"}]
    assert report.summary["retractions"] == 0 and "- taken out of the file with no retraction (2): `w91001` (issue 5), `w91002` (issue 6)" in report.markdown()


def test_a_previous_release_that_lists_no_entries_is_said_once_and_is_not_taken_for_one_without_entries(tmp_path):
    old, new = pair(tmp_path)
    drop_community(old)  # (a release made before the entries were recorded)
    set_community(new, reports=[report_entry("w91001", 5)], retracted=[retraction_entry("w91002", 6)])
    report = run(old, new)
    sentence = "the previous release does not list its community entries"
    assert report.summary["community"]["note"] == sentence
    assert report.summary["community"]["added"] == [] and report.summary["community"]["retracted"] == [] and report.summary["retractions"] == 0  # (not "everything is new")
    assert report.markdown().count(sentence) == 1 and json.loads(report.json_text())["summary"]["community"]["note"] == sentence


def test_the_entries_of_the_first_release_that_records_them_are_listed_as_recorded_for_the_first_time_and_never_as_additions(tmp_path):
    """The previous release is one made before the field existed: whatever the file holds now was recorded before, and the report cannot tell when. It lists the entries (their
    number and each of them) as recorded in this release for the first time, and none as added or retracted."""
    old, new = pair(tmp_path)
    drop_community(old)
    set_community(new, reports=[report_entry("w91001", 5), report_entry("w91002", 6, kind="tier")], retracted=[retraction_entry("w91003", 7, reason="duplicate")])
    report = run(old, new)
    community = report.summary["community"]
    assert community["first"] == {
        "reports": [{"key": "w91001", "issue": 5}, {"key": "w91002", "issue": 6}],
        "retracted": [{"key": "w91003", "issue": 7, "reason": "duplicate"}],
    }
    assert community["added"] == [] and community["retracted"] == [] and community["deleted"] == [] and report.summary["retractions"] == 0
    text = report.markdown()
    assert "- recorded in this release for the first time, reports (2): `w91001` (issue 5), `w91002` (issue 6)" in text
    assert "- recorded in this release for the first time, retracted (1): `w91003` (issue 7, duplicate)" in text
    assert "- added (" not in text and "- retracted (" not in text  # (not one of them an addition or a retraction)
    assert text.count("the previous release does not list its community entries") == 1  # (and the sentence is said once, as before)
    assert json.loads(report.json_text())["summary"]["community"]["first"] == community["first"]


def test_the_markdown_lists_twenty_of_the_entries_recorded_for_the_first_time_and_the_json_all_of_them(tmp_path):
    old, new = pair(tmp_path)
    drop_community(old)
    set_community(new, reports=[report_entry(f"w{91000 + number}", 100 + number) for number in range(25)])
    report = run(old, new)
    assert len(report.summary["community"]["first"]["reports"]) == 25
    text = report.markdown()
    assert "- recorded in this release for the first time, reports (25): " in text and "`w91019` (issue 119)" in text and "`w91020`" not in text
    assert "and 5 more (the JSON lists them all)" in text


def test_nothing_is_recorded_for_the_first_time_when_the_previous_release_lists_its_entries_or_the_new_one_does_not(tmp_path):
    old, new = pair(tmp_path / "both")
    set_community(new, reports=[report_entry("w91001", 5)])
    report = run(old, new)
    assert report.summary["community"]["first"] == {"reports": [], "retracted": []} and report.summary["community"]["added"] == [{"key": "w91001", "issue": 5}]  # (an addition)
    assert "recorded in this release for the first time" not in report.markdown()
    old, new = pair(tmp_path / "neither")
    drop_community(old)
    drop_community(new)
    report = run(old, new)
    assert report.summary["community"]["first"] == {"reports": [], "retracted": []} and "recorded in this release for the first time" not in report.markdown()


def test_a_new_release_that_lists_no_entries_is_said_too(tmp_path):
    old, new = pair(tmp_path)
    drop_community(new)
    report = run(old, new)
    assert report.summary["community"]["note"] == "the new release does not list its community entries" and report.markdown().count("does not list its community entries") == 1


def test_two_releases_that_list_their_entries_say_nothing_of_the_kind(tmp_path):
    old, new = pair(tmp_path)
    assert run(old, new).summary["community"]["note"] is None and "does not list" not in run(old, new).markdown()


def test_a_first_release_has_no_entries_to_compare_and_says_nothing_about_them(tmp_path):
    new = make_release(tmp_path / "new", tag="data-2026-10-17")
    set_community(new, reports=[report_entry("w91001", 5)])
    report = results_diff.diff(None, new)
    assert report.summary["community"] == {
        "added": [], "retracted": [], "deleted": [], "changed": [], "first": {"reports": [], "retracted": []}, "strict_gained": [], "strict_lost": [], "note": None,
    }  # fmt: skip
    assert "Community evidence" not in report.markdown()


def test_the_markdown_lists_twenty_entries_with_their_issues_and_the_json_all_of_them(tmp_path):
    old, new = pair(tmp_path)
    entries = [report_entry(f"w{91000 + number}", 100 + number) for number in range(25)]
    set_community(new, reports=entries)
    report = run(old, new)
    assert len(report.summary["community"]["added"]) == 25 and len(json.loads(report.json_text())["summary"]["community"]["added"]) == 25
    text = report.markdown()
    assert "- added (25): " in text and "`w91000` (issue 100)" in text and "`w91019` (issue 119)" in text and "`w91020`" not in text
    assert "and 5 more (the JSON lists them all)" in text


# ---- new and removed trios and tiers -------------------------------------------------------------------------------------------------------


def test_a_trio_the_old_release_lacks_is_one_new_record_and_its_rows_are_counted_not_listed(tmp_path):
    old, new = pair(tmp_path)
    copy_trio(new, "clr-shd-ber")
    report = run(old, new)
    (record,) = of_kind(report, "trio")
    rows = sum(len(shard(new, name).doc["scenarios"]) for name in SHARDS)
    assert record["trio"] == "clr-shd-ber" and record["change"] == "new" and record["tiers"] == [0, 4, 10] and record["scenarios"] == rows
    assert record["causes"] == ["new"] and record["primary"] == "new" and record["flag"] is None
    assert of_kind(report, "scenario") == [] and report.summary["new_trios"] == 1 and report.summary["by_cause"]["new"] == 1


def test_a_trio_the_new_release_lacks_is_listed_as_removed(tmp_path):
    old, new = pair(tmp_path)
    copy_trio(old, "clr-shd-ber")
    (record,) = of_kind(run(old, new), "trio")
    assert record["trio"] == "clr-shd-ber" and record["change"] == "removed" and record["causes"] == []
    remove_trio(old, "clr-shd-ber")
    assert of_kind(run(old, new), "trio") == []


def test_a_tier_the_old_release_lacks_is_a_new_tier_and_its_rows_are_not_listed_one_by_one(tmp_path):
    old, new = pair(tmp_path)
    drop_tier(old, 10)
    report = run(old, new)
    (record,) = of_kind(report, "tier")
    rows = sum(len([r for r in shard(new, name).doc["scenarios"] if r[2] == 10]) for name in SHARDS)
    assert record["trio"] == SLUG and record["tier"] == 10 and record["change"] == "new" and record["scenarios"] == rows > 0
    assert record["causes"] == ["new"]
    assert of_kind(report, "scenario") == [] and of_kind(report, "runner-up") == [] and report.summary["new_tiers"] == 1


def test_a_first_release_has_every_trio_new(tmp_path):
    new = make_release(tmp_path / "new", tag="data-2026-10-17")
    report = results_diff.diff(None, new)
    (record,) = of_kind(report, "trio")
    assert record["change"] == "new" and report.summary["previous"] is None and report.summary["new_trios"] == 1
    assert "first release" in report.markdown().lower()


def test_a_scenario_that_appears_or_goes_is_classified_like_a_changed_one(tmp_path):
    old, new = pair(tmp_path)
    file = shard(old, "strict-own")
    file.drop_rows(lambda row: not (row[1] == "tank" and row[3] == "1h-shield"))  # the old strict shard had no shield rows of the Tank
    file.save()
    report = run(old, new)
    added = [c for c in of_kind(report, "scenario") if c["change"] == "added"]
    assert len(added) == 9 and all(c["fields"] == ["row"] and c["F"][0] is None and c["flag"] == "solver-diff" for c in added)  # (nothing explains it)
    strict = shard(new, "strict-own")
    kit = [key for key in strict.kit(strict.row("OGR", "tank", 4, "1h-shield")) if key]
    change_item(new, kit[0])
    explained = [c for c in of_kind(run(old, new), "scenario") if c["change"] == "added" and c["view"]["race"] == "OGR" and c["view"]["tier"] == 4]
    assert explained and explained[0]["causes"] == ["data"]
    gone = run(new, old)  # the other way round, the same rows go
    assert len([c for c in of_kind(gone, "scenario") if c["change"] == "removed"]) == 9


# ---- the default pick and the runner-ups ---------------------------------------------------------------------------------------------------


def test_a_change_of_the_default_pick_is_classified(tmp_path):
    old, new = pair(tmp_path)
    change_item(new)
    file = shard(new, "strict-own")
    file.set_place(file.row(*OGR), "HEAD", OTHER_ITEM)
    file.save()
    edit(new / SLUG / "defaults.json", lambda d: d.update(F=d["F"] + 1.5, margin=d["margin"] + 1.5))
    report = run(old, new)
    (change,) = of_kind(report, "default", trio=SLUG)
    assert change["fields"] == ["F", "kit", "margin"] and change["causes"] == ["data"] and change["flag"] is None
    assert change["old"]["race"] == change["new"]["race"] == "OGR" and change["new"]["F"] == change["old"]["F"] + 1.5
    assert change["kit"] == [{"place": "HEAD", "old": HEAD_ITEM, "new": OTHER_ITEM}]


def test_a_default_race_that_changes_with_the_same_inputs_is_a_solver_diff(tmp_path):
    old, new = pair(tmp_path)
    edit(new / SLUG / "defaults.json", lambda d: d.update(race="TRL", runner_up_race="OGR", F=d["F"] - 5))
    (change,) = of_kind(run(old, new), "default")
    assert "race" in change["fields"] and "runner_up_race" in change["fields"] and change["flag"] == "solver-diff" and change["causes"] == []


def test_a_runner_up_that_changes_is_a_record_with_the_places_that_differ(tmp_path):
    old, new = pair(tmp_path)
    edit_runnerups(new, "balanced", lambda doc: runnerup_place(doc, 4, "OGR", "HEAD", [("w91002", -3.5), ("w91003", -6.25)]))
    report = run(old, new)
    (change,) = of_kind(report, "runner-up")
    assert (change["trio"], change["role"], change["tier"], change["race"]) == (SLUG, "balanced", 4, "OGR")
    assert change["fields"] == ["places"] and change["causes"] == [] and change["flag"] == "solver-diff"
    (place,) = change["places"]
    assert place["place"] == "HEAD" and place["new"] == [["w91002", -3.5], ["w91003", -6.25]] and place["old"] != place["new"]
    assert {key for key, _ in place["old"] + place["new"]} <= set(change["items"])


def test_the_same_runner_ups_in_another_order_with_the_same_deltas_are_a_tie(tmp_path):
    old, new = pair(tmp_path)
    for folder, order in ((old, ["w91002", "w91003"]), (new, ["w91003", "w91002"])):
        edit_runnerups(folder, "balanced", lambda doc, order=order: runnerup_place(doc, 4, "OGR", "HEAD", [(key, -3.5) for key in order]))
    (change,) = of_kind(run(old, new), "runner-up")
    assert change["flag"] == "tie"


def test_a_runner_up_item_that_changed_in_the_catalog_is_a_data_cause(tmp_path):
    old, new = pair(tmp_path)
    for folder in (old, new):
        edit_runnerups(folder, "balanced", lambda doc: runnerup_place(doc, 4, "OGR", "HEAD", [(OTHER_ITEM, -3.5)]))
    change_item(new, OTHER_ITEM)
    edit_runnerups(new, "balanced", lambda doc: runnerup_place(doc, 4, "OGR", "HEAD", [(OTHER_ITEM, -4.5)]))
    (change,) = of_kind(run(old, new), "runner-up")
    assert change["causes"] == ["data"] and change["flag"] is None


def test_a_runner_up_moves_with_the_kit_it_is_swapped_from(tmp_path):
    """The deltas are against the kit: when an item of the kit changed in the catalog, every swap of the view moves with it."""
    old, new = pair(tmp_path)
    change_item(new)  # the head of the Ogre's kit
    edit_runnerups(new, "balanced", lambda doc: runnerup_place(doc, 4, "OGR", "FACE", [("w91002", -9.0)]))
    runnerups = [c for c in of_kind(run(old, new), "runner-up") if c["race"] == "OGR" and c["tier"] == 4]
    assert runnerups and runnerups[0]["causes"] == ["data"]


# ---- item, source and evidence records ------------------------------------------------------------------------------------------------------


def test_a_changed_name_or_source_is_an_item_record_with_a_data_cause_and_moves_no_pick(tmp_path):
    old, new = pair(tmp_path)
    table = ItemTable(new / "items.json")
    record = table.record(HEAD_ITEM)
    record["name"] = "Invented Renamed Cap"
    record["source"] = {"drops": ["Invented Keep"]}
    table.save()
    report = run(old, new)
    (item,) = of_kind(report, "item")
    assert item["key"] == HEAD_ITEM and item["fields"] == ["name", "source"] and item["causes"] == ["data"] and item["evidence"] is None
    assert of_kind(report, "scenario") == [] and report.summary["by_kind"]["item"] == 1


def test_an_item_added_to_or_removed_from_the_catalog_is_listed(tmp_path):
    old, new = pair(tmp_path)
    table = ItemTable(new / "items.json")
    table.remove(OTHER_ITEM)
    table.save()
    add_invented_item(new, "w91009", strict=False)
    report = run(old, new)
    changes = {c["key"]: c["change"] for c in of_kind(report, "item")}
    assert changes == {OTHER_ITEM: "removed", "w91009": "added"}
    assert all(c["causes"] == ["data"] for c in of_kind(report, "item"))


def test_the_arrival_of_an_item_changes_with_the_tier_rules_and_is_a_rule_cause(tmp_path):
    old, new = pair(tmp_path)
    change_rule(new, "tier.max_fresh_drop", 3)
    for name in SHARDS:
        file = shard(new, name)
        for item in file.doc["items"]:
            if item[0] == HEAD_ITEM:
                item[4] = 3
        file.save()
    (item,) = of_kind(run(old, new), "item")
    assert item["key"] == HEAD_ITEM and item["fields"] == ["arrival"] and item["causes"] == ["rule"]


def test_the_arrival_of_an_item_that_moves_with_no_tier_rule_changed_is_data(tmp_path):
    old, new = pair(tmp_path)
    for name in SHARDS:
        file = shard(new, name)
        for item in file.doc["items"]:
            if item[0] == HEAD_ITEM:
                item[4] = 3
        file.save()
    (item,) = of_kind(run(old, new), "item")
    assert item["fields"] == ["arrival"] and item["causes"] == ["data"]


# ---- nothing capped, the top 20, the public report --------------------------------------------------------------------------------------------


def many_changes(tmp_path, count: int):
    """A new release in which ``count`` scenarios of the wiki shard have a different value, each by an amount of its own."""
    old, new = pair(tmp_path)
    file = shard(new)
    for number, row in enumerate(file.doc["scenarios"][:count]):
        file.set_value(row, row[5] + (number + 1) * 0.25)
    file.save()
    return old, new


def table_rows(text: str) -> list[list[str]]:
    """The rows of the table after the heading of the largest changes, without the header and the rule under it."""
    lines = [line for line in text.split("largest changes of F")[1].splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines[2:]]


def test_every_change_is_in_the_json_and_the_markdown_says_how_many_it_shows(tmp_path):
    old, new = many_changes(tmp_path, 45)
    report = run(old, new)
    assert len(report.changes) == 45 and report.summary["changes"] == 45
    data = json.loads(report.json_text())
    assert len(data["changes"]) == 45 and data["summary"]["changes"] == 45 and data["release"] == "data-2026-10-17" and data["previous"] == "data-2026-10-10"
    text = report.markdown()
    assert "The 20 largest changes of F (of 45)" in text and len(table_rows(text)) == 20


def test_the_twenty_largest_changes_are_shown_largest_first(tmp_path):
    old, new = many_changes(tmp_path, 30)
    report = run(old, new)
    top = report.top()
    assert len(top) == 20 and [abs(c["delta"]) for c in top] == sorted((abs(c["delta"]) for c in report.changes), reverse=True)[:20]
    assert abs(top[0]["delta"]) == 30 * 0.25 and abs(top[-1]["delta"]) == 11 * 0.25
    shown = [float(row[4]) for row in table_rows(report.markdown())]
    assert shown == [c["delta"] for c in top] and shown[:3] == [7.5, 7.25, 7.0]


def test_a_few_changes_show_only_what_there_is(tmp_path):
    old, new = many_changes(tmp_path, 3)
    report = run(old, new)
    assert len(report.top()) == 3
    assert "The 3 largest changes of F (of 3)" in report.markdown() and len(table_rows(report.markdown())) == 3


def test_the_report_holds_no_private_data(tmp_path):
    old, new = pair(tmp_path)
    table = ItemTable(new / "items.json")
    table.set_evidence(HEAD_ITEM, "strict", ["community-report"])
    table.save()
    nudge(new)
    report = run(old, new)
    secrets = [load(new / "items.json")["inputs"], load(new / SLUG / "engine-l50.json")["inputs"], "ef" * 16, "cd" * 16, SHA_A]  # the fingerprints of the inputs
    for text in (report.markdown(), report.json_text()):
        assert "fingerprint" not in text.lower() and "seen" not in text.lower()
        assert all(secret not in text for secret in secrets)


def test_the_json_is_deterministic_and_lists_the_changes_in_a_fixed_order(tmp_path):
    old, new = many_changes(tmp_path, 12)
    first, second = run(old, new), run(old, new)
    assert first.json_text() == second.json_text() and first.markdown() == second.markdown()
    document = json.loads(first.json_text())
    assert list(document) == ["format", "release", "previous", "summary", "changes"] and document["format"] == 1
    keys = [(c["trio"], c["view"]["evidence"], c["view"]["buffs"], c["view"]["race"], c["view"]["role"], c["view"]["tier"], c["view"]["setup"]) for c in document["changes"]]
    assert keys == sorted(keys) and len(set(keys)) == 12


def test_the_summary_counts_the_changes_by_kind_and_by_primary_cause(tmp_path):
    old, new = pair(tmp_path)
    change_item(new)
    nudge(new)  # explained by the item
    nudge(new, 2.0, row=NO_HEAD_ITEM)  # explained by nothing
    report = run(old, new)
    summary = report.summary
    assert summary["by_kind"] == {"scenario": 2, "item": 1} and summary["changes"] == 3
    assert summary["by_cause"] == {"code": 0, "rule": 0, "data": 2, "community": 0, "new": 0, "unexplained": 1}
    assert summary["solver_diffs"] == 1 and summary["ties"] == 0 and summary["community_only"] == 0
    assert summary["inputs"] == {"code": False, "rules": [], "game_patch": None, "catalog_date": None, "rules_version": None}


def test_a_note_the_caller_adds_is_in_both_renderings_and_only_then(tmp_path):
    old, new = pair(tmp_path)
    report = run(old, new)
    assert "note" not in json.loads(report.json_text()) and "Note:" not in report.markdown()
    report.note = "the release data-2026-10-03 is in releases/, but its asset is not here"
    assert json.loads(report.json_text())["note"] == report.note and f"Note: {report.note}" in report.markdown()
    assert list(json.loads(report.json_text())) == ["format", "release", "previous", "note", "summary", "changes"]


# ---- the rules the solver never reads ---------------------------------------------------------------------------------------------------
#
# A change to a rule that no pick uses must not explain a pick: it would hide a solver diff. Every rule of the rules file is listed here in one of
# three groups, so that a new rule cannot be left out: read by the solver in every pick, read in the picks of a scope (RULE_SCOPES), or read by the
# solver in none (it uses a constant that mirrors the rule, which the tests compare, or only the export and the site read the rule).

REPO = Path(__file__).resolve().parents[2]
SCOPED_RULES = {
    "race.iksar_ac_bonus", "race.iksar_ac_placement", "monk.weight_curve", "monk.bonus_placement", "haste.cap_pct_with_monk", "haste.cap_pct",
    "weapons.dual_wield_factor", "tier.weapon_damage_pct", "tier.stat_rule", "tier.weight_floor", "tier.negatives_scale",
}  # fmt: skip
EVERY_PICK_RULES = {
    "level.current", "mana.wis_bands", "mana.stat_by_class", "ac.softcap.combat_stability_pct", "ac.softcap.physical_enhancement_pct",
    "ac.softcap.pe_for_caster_only_trios", "ac.shield.offhand_raises_cap", "haste.worn_per_tier", "regen.gear_caps", "regen.per_tier", "regen.value_minutes",
    "resist.cap", "buffs.min_duration_minutes", "buffs.max_slots", "roles.templates", "weapons.damage_weight",
}  # fmt: skip
NEVER_READ_RULES = {
    "naked.cap", "naked.rule", "hp.pools_counted", "hp.sta_curve", "mana.pools_counted", "mana.base_l50", "mana.per_stat_l50", "end.formula",
    "ac.sheet.item_mult", "ac.sheet.defense_div", "ac.sheet.spell_ac_div", "ac.sheet.agi_div", "ac.softcap.past_cap_rate", "stats.knee", "stats.hard_cap",
    "stats.str_to_atk", "stats.agi_to_ac", "stats.dex_post255_slope", "haste.unbound_alacrity", "packrat.pct_per_rank", "tier.accuracy_pct",
    "tier.socket_open", "tier.arrival", "tier.max_fresh_drop", "tier.exp_needed", "roles.balanced",
}  # fmt: skip
PICKS = [
    results_diff.Scope(frozenset({"PAL", "MNK", "BER"}), "OGR", 4, "dw"),
    results_diff.Scope(frozenset({"WAR", "CLR", "DRU"}), "HUM", 0, "2h"),
    results_diff.Scope(frozenset({"BRD", "BST", "BER"}), "IKS", 10, "dw"),
    results_diff.Scope(frozenset({"BRD", "BST", "BER"})),
]


def rule_ids() -> list[str]:
    return [rule["id"] for rule in json.loads((REPO / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"]]


@pytest.mark.parametrize("rule", ["tier.exp_needed", "tier.socket_open", "tier.arrival", "tier.accuracy_pct", "tier.max_fresh_drop"])
def test_a_change_to_a_rule_the_solver_never_reads_hides_no_solver_diff(tmp_path, rule):
    """The reviewer's repro: one F raised by 7.5, and a rule changed that only the export and the site read. The rule is no reason for the pick."""
    old, new = pair(tmp_path)
    change_rule(old, rule, 1)
    change_rule(new, rule, 2)
    nudge(new, 7.5)
    report = run(old, new)
    (change,) = of_kind(report, "scenario")
    assert change["delta"] == 7.5 and change["causes"] == [] and change["flag"] == "solver-diff"
    assert report.summary["solver_diffs"] == 1 and report.summary["inputs"]["rules"] == [rule]  # (the change of the rule is still reported)
    assert "SOLVER DIFF" in report.markdown()


def test_a_change_of_the_status_of_a_rule_alone_is_no_change_of_the_rule(tmp_path):
    old, new = pair(tmp_path)
    document = assemble.read_release_json(new)
    document["rules"]["monk.weight_curve"]["status"] = "active"
    assemble.write_release_json(new, document)
    nudge(new)
    report = run(old, new)
    assert report.summary["inputs"]["rules"] == []
    (change,) = of_kind(report, "scenario")
    assert change["causes"] == [] and change["flag"] == "solver-diff"


def test_a_change_of_the_levels_of_a_rule_is_a_change_of_the_rule(tmp_path):
    old, new = pair(tmp_path)
    document = assemble.read_release_json(new)
    document["rules"]["monk.weight_curve"]["levels"] = {"55": {"softcap_stones": 20}}
    assemble.write_release_json(new, document)
    nudge(new)
    report = run(old, new)
    assert report.summary["inputs"]["rules"] == ["monk.weight_curve"] and of_kind(report, "scenario")[0]["causes"] == ["rule"]


def test_every_rule_of_the_rules_file_is_in_exactly_one_group():
    assert sorted(SCOPED_RULES | EVERY_PICK_RULES | NEVER_READ_RULES) == sorted(rule_ids())
    assert len(SCOPED_RULES) + len(EVERY_PICK_RULES) + len(NEVER_READ_RULES) == len(rule_ids())


def test_the_report_puts_each_rule_in_the_picks_the_table_says():
    for rule in EVERY_PICK_RULES:
        assert all(results_diff.rule_in_pick(rule, scope) for scope in PICKS), rule
    for rule in NEVER_READ_RULES:
        assert not any(results_diff.rule_in_pick(rule, scope) for scope in PICKS), rule
    for rule in SCOPED_RULES:
        assert rule in results_diff.RULE_SCOPES and any(results_diff.rule_in_pick(rule, scope) for scope in PICKS), rule  # (where they apply: see above)
    assert set(results_diff.RULE_SCOPES) == SCOPED_RULES
    assert results_diff.UNREAD == NEVER_READ_RULES


def hashed_literals() -> set[str]:
    """The string constants, docstrings aside, of the source files whose code hash is in the fingerprint of the chunks: what the solver can read by name."""
    from trioforge.precompute import grid

    found: set[str] = set()
    for path in grid.code_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
        }  # fmt: skip
        found |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings}
    return found


def test_the_rules_the_code_of_the_solver_names_are_the_rules_that_are_in_some_pick():
    named = hashed_literals() & set(rule_ids())
    assert named == SCOPED_RULES | EVERY_PICK_RULES, sorted(named ^ (SCOPED_RULES | EVERY_PICK_RULES))


def test_a_solve_reads_no_rule_of_the_never_group(tmp_path, monkeypatch):
    """The group is checked against what a real solve reads: a Monk trio, an Iksar, three setups, three tiers, the solves and the runner-ups."""
    from test_precompute import CATALOG, context_of

    from trioforge.precompute import grid
    from trioforge.rules import Rules

    read: list[str] = []
    real = Rules.get

    def spy(self, id, *args, **kwargs):
        read.append(id)
        return real(self, id, *args, **kwargs)

    monkeypatch.setattr(Rules, "get", spy)
    ctx = context_of(tmp_path, CATALOG)
    for key, races in (
        (grid.ChunkKey("wiki", "own", "balanced", "dw", 4), ["IKS", "OGR"]),
        (grid.ChunkKey("wiki", "group", "tank", "1h-shield", 0), ["OGR"]),
        (grid.ChunkKey("strict", "own", "melee", "2h", 10), ["HUM"]),
    ):
        row = grid.solve_chunk(ctx, key, races)["rows"][0]
        if key.buffs == "own":  # (the runner-ups are of the own-buffs views)
            entry = grid.RunnerupInput(races[0], key.setup, tuple(row["kit"]), tuple(row["buffs"]), row["haste"])
            grid.runnerup_chunk(ctx, key.role, key.tier, [entry])
    assert read and not set(read) & NEVER_READ_RULES, sorted(set(read) & NEVER_READ_RULES)
    assert set(read) <= SCOPED_RULES | EVERY_PICK_RULES


# ---- the seals and the bundles --------------------------------------------------------------------------------------------------------------


def set_seal(folder: Path, place: str = "HEAD", text: str = "MANA x2", *, role: str = "balanced", tier: str = "4") -> None:
    edit(folder / SLUG / "robust.json", lambda d: d["roles"][role][tier].update({place: text}))


def set_bundle(folder: Path) -> None:
    edit(folder / SLUG / "engine-l50.json", lambda b: b["constants"].update(hp_pool_constant="1/1"))


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_seal_that_changes_is_a_record_with_the_places_that_differ(tmp_path):
    old, new = pair(tmp_path)
    set_seal(new, "HEAD", "MANA x2")
    report = run(old, new)
    (change,) = of_kind(report, "seal")
    assert change["trio"] == SLUG and change["role"] == "balanced" and change["tier"] == 4 and change["race"] == "OGR" and change["change"] == "changed"
    assert change["places"] == [{"place": "HEAD", "old": "robust", "new": "MANA x2"}] and change["fields"] == ["places"]
    assert change["causes"] == [] and change["flag"] == "solver-diff"  # the same inputs gave other seals: a bug until explained
    assert report.summary["by_kind"] == {"seal": 1} and report.summary["solver_diffs"] == 1
    assert "SOLVER DIFF" in report.markdown() and "seal" in report.markdown()


def test_every_place_of_a_seal_that_differs_is_listed_and_the_other_roles_and_tiers_are_left_alone(tmp_path):
    old, new = pair(tmp_path)
    set_seal(new, "HEAD", "MANA x2")
    set_seal(new, "CHEST", "AC x2")
    set_seal(new, "BACK", "AC x2", role="tank", tier="10")
    report = run(old, new)
    first, second = of_kind(report, "seal")
    assert (first["role"], first["tier"], [p["place"] for p in first["places"]]) == ("balanced", 4, ["HEAD", "CHEST"])
    assert (second["role"], second["tier"], [p["place"] for p in second["places"]]) == ("tank", 10, ["BACK"])


@pytest.mark.parametrize(
    ("apply", "causes"),
    [
        (lambda folder: change_rule(folder, "monk.weight_curve"), ["rule"]),
        (lambda folder: change_release_json(folder, code_hash="9f" * 32), ["code"]),
        (lambda folder: change_release_json(folder, game_patch="2026-10-01"), ["data"]),
    ],
)
def test_a_seal_that_changes_with_a_new_input_has_that_cause(tmp_path, apply, causes):
    old, new = pair(tmp_path)
    apply(new)
    set_seal(new)
    (change,) = of_kind(run(old, new), "seal")
    assert change["causes"] == causes and change["flag"] is None


def test_a_seal_that_moves_with_the_item_of_its_pick_is_a_data_cause(tmp_path):
    """The seal of the Ogre's balanced pick at +4 goes with the kit of that pick: an item in it that changed explains the seal."""
    old, new = pair(tmp_path)
    kit = shard(old, "strict-own").kit(shard(old, "strict-own").row(*OGR))
    worn = next(key for key in kit if key)
    change_item(new, worn)
    set_seal(new)
    (change,) = of_kind(run(old, new), "seal")
    assert change["causes"] == ["data"]


def test_a_seal_that_one_release_lacks_is_added_or_removed(tmp_path):
    old, new = pair(tmp_path)

    def drop(document):
        del document["roles"]["balanced"]["10"]

    edit(new / SLUG / "robust.json", drop)
    report = run(old, new)
    (change,) = of_kind(report, "seal")
    assert (change["role"], change["tier"], change["change"]) == ("balanced", 10, "removed") and "places" not in change
    assert run(new, old).changes[0]["change"] == "added"


def test_a_default_race_that_moves_moves_the_seals_with_it(tmp_path):
    old, new = pair(tmp_path)
    edit(new / SLUG / "robust.json", lambda d: d.update(race="TRL"))
    seals = of_kind(run(old, new), "seal")
    assert seals and all(change["race"] == ["OGR", "TRL"] and "race" in change["fields"] for change in seals)


def test_a_bundle_that_changes_is_named_with_its_two_hashes_and_never_its_content(tmp_path):
    old, new = pair(tmp_path)
    set_bundle(new)
    report = run(old, new)
    (change,) = of_kind(report, "bundle")
    assert change["trio"] == SLUG and change["file"] == "engine-l50.json" and change["change"] == "changed"
    assert change["sha256"] == [sha256_of(old / SLUG / "engine-l50.json"), sha256_of(new / SLUG / "engine-l50.json")]
    assert change["causes"] == [] and change["flag"] == "solver-diff"  # nothing the bundle is made from changed
    assert report.summary["by_kind"] == {"bundle": 1} and report.summary["solver_diffs"] == 1
    assert "1/1" not in report.json_text() and "1/1" not in report.markdown()  # the hash, not the content


@pytest.mark.parametrize(
    ("apply", "causes"),
    [
        (lambda folder: change_release_json(folder, code_hash="9f" * 32), ["code"]),
        (lambda folder: change_rule(folder, "tier.exp_needed"), ["rule"]),  # the bundle holds the tier rules the solver itself does not read
        (lambda folder: change_release_json(folder, game_patch="2026-10-01"), ["data"]),
    ],
)
def test_a_bundle_that_changes_with_a_new_input_has_that_cause(tmp_path, apply, causes):
    old, new = pair(tmp_path)
    apply(new)
    set_bundle(new)
    (change,) = of_kind(run(old, new), "bundle")
    assert change["causes"] == causes and change["flag"] is None


def test_a_bundle_that_one_release_lacks_is_added_or_removed(tmp_path):
    old, new = pair(tmp_path)
    (new / SLUG / "engine-l50.json").rename(new / SLUG / "engine-l55.json")
    report = run(old, new)
    kinds = {(c["file"], c["change"]) for c in of_kind(report, "bundle")}
    assert kinds == {("engine-l50.json", "removed"), ("engine-l55.json", "added")}
    added = next(c for c in of_kind(report, "bundle") if c["change"] == "added")
    assert added["sha256"][0] is None and added["sha256"][1] == sha256_of(new / SLUG / "engine-l55.json") and added["causes"] == ["new"]


def test_the_seals_and_the_bundles_of_a_new_trio_are_counted_with_it(tmp_path):
    old, new = pair(tmp_path)
    copy_trio(new, "war-clr-pal")
    report = run(old, new)
    assert not of_kind(report, "seal") and not of_kind(report, "bundle")  # (the trio is one record: its files are not listed)


def test_nothing_about_the_seals_and_the_bundles_is_capped(tmp_path):
    old, new = pair(tmp_path)
    for slug in ("war-clr-pal", "war-clr-rng"):
        copy_trio(old, slug)
        copy_trio(new, slug)
    for slug in (SLUG, "war-clr-pal", "war-clr-rng"):
        edit(new / slug / "engine-l50.json", lambda b: b["constants"].update(hp_pool_constant="1/1"))
        for tier in ("4", "10"):
            for role in ("balanced", "tank", "melee"):
                edit(new / slug / "robust.json", lambda d: d["roles"][role][tier].update(HEAD="MANA x2"))
    report = run(old, new)
    assert len(of_kind(report, "bundle")) == 3 and len(of_kind(report, "seal")) == 18
    assert len(json.loads(report.json_text())["changes"]) == 21 and report.summary["changes"] == 21


# ---- a trial ----------------------------------------------------------------------------------------------------------------------------


def test_the_report_of_a_trial_is_headed_trial_in_both_renderings_and_a_release_is_not(tmp_path):
    old, new = pair(tmp_path / "trial", new={"trial": True})
    nudge(new)
    report = run(old, new)
    text = report.markdown()
    assert text.splitlines()[0].startswith("# TRIAL") and "no release" in text.lower()
    document = json.loads(report.json_text())
    assert document["trial"] is True and list(document)[:4] == ["format", "release", "previous", "trial"]
    old, new = pair(tmp_path / "release")
    nudge(new)
    report = run(old, new)
    assert "TRIAL" not in report.markdown() and "trial" not in json.loads(report.json_text())
    assert report.markdown().splitlines()[0].startswith("# Results diff")


def test_a_rules_version_that_changes_is_a_rule_cause_of_the_bundles_and_a_status_alone_makes_no_solver_diff(tmp_path):
    """The bundle's inputs are one hash over the whole rules file, a status and a note included: when only those changed, every bundle changed, and not by a bug."""
    old, new = pair(tmp_path, new={"rules_version": "2026-10-20"})
    document = assemble.read_release_json(new)
    document["rules"]["monk.weight_curve"]["status"] = "active"  # (not a change of the rule)
    assemble.write_release_json(new, document)
    set_bundle(new)
    report = run(old, new)
    (change,) = of_kind(report, "bundle")
    assert change["causes"] == ["rule"] and change["flag"] is None
    assert report.summary["solver_diffs"] == 0 and report.summary["inputs"]["rules"] == []
    assert report.summary["inputs"]["rules_version"] == ["2026-10-13", "2026-10-20"]


def test_a_rules_version_that_changes_is_no_cause_of_a_pick(tmp_path):
    old, new = pair(tmp_path, new={"rules_version": "2026-10-20"})
    nudge(new)
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == [] and change["flag"] == "solver-diff"  # (the version is a label: the rules that it names are compared, one by one)


# ---- an evidence change explains a pick only where it changes the pool the pick was made from ------------------------------------------------------
#
# The strict pool holds the items of level strict, the wiki pool the items of level strict or wiki. An item that moves from wiki to strict is in the wiki pool before
# and after: a wiki pick that wears it changed for another reason, and a solver diff must not be hidden behind it.


def flag(folder: Path, key: str, level: str = "strict") -> None:
    """Move an item to another evidence level the way a seen flag does (no community entry: nothing public says why)."""
    table = ItemTable(folder / "items.json")
    table.set_evidence(key, level, ["seen-in-game"] if level == "strict" else ())
    table.save()


def view(report, evidence: str):
    (change,) = [c for c in of_kind(report, "scenario") if c["view"]["evidence"] == evidence]
    return change


def test_an_item_that_moves_from_wiki_to_strict_explains_a_strict_pick_and_not_a_wiki_one(tmp_path):
    old, new = pair(tmp_path)
    for folder in (old, new):
        add_invented_item(folder, "w91001", strict=False)
    flag(new, "w91001")
    pick(new, "w91001")  # the wiki pool held the item before and after
    pick(new, "w91001", name="strict-own")  # the strict pool gained it
    report = run(old, new)
    assert view(report, "wiki")["causes"] == [] and view(report, "wiki")["flag"] == "solver-diff"
    assert view(report, "strict")["causes"] == ["data"] and view(report, "strict")["flag"] is None


def test_an_item_that_falls_from_strict_to_wiki_explains_a_strict_pick_and_not_a_wiki_one(tmp_path):
    old, new = pair(tmp_path)
    for folder in (old, new):
        add_invented_item(folder, "w91001", strict=False)
    flag(old, "w91001")
    pick(old, "w91001")
    pick(old, "w91001", name="strict-own")
    report = run(old, new)
    assert view(report, "wiki")["causes"] == [] and view(report, "wiki")["flag"] == "solver-diff"
    assert view(report, "strict")["causes"] == ["data"]


def test_an_item_that_leaves_the_wiki_pool_explains_a_wiki_pick_and_not_a_strict_one(tmp_path):
    old, new = pair(tmp_path)
    for folder in (old, new):
        add_invented_item(folder, "w91001", strict=False)
    flag(new, "w91001", "disputed")  # in neither pool now
    pick(old, "w91001")
    pick(old, "w91001", name="strict-own")  # (the strict pool did not hold it: a wiki item)
    report = run(old, new)
    assert view(report, "wiki")["causes"] == ["data"]
    assert view(report, "strict")["causes"] == [] and view(report, "strict")["flag"] == "solver-diff"


def test_a_change_of_a_field_the_solver_reads_explains_every_pick_that_wears_the_item(tmp_path):
    old, new = pair(tmp_path)
    for folder in (old, new):
        add_invented_item(folder, "w91001", strict=False)
    table = ItemTable(new / "items.json")
    table.set_stats("w91001", AC=99)
    table.save()
    pick(new, "w91001")
    pick(new, "w91001", name="strict-own")
    report = run(old, new)
    assert view(report, "wiki")["causes"] == ["data"] and view(report, "strict")["causes"] == ["data"]


def test_an_item_added_to_the_catalog_explains_the_picks_of_the_pools_it_joins(tmp_path):
    old, new = pair(tmp_path)
    add_invented_item(new, "w91002", strict=False)  # a wiki item, new in the catalog
    pick(new, "w91002")
    pick(new, "w91002", name="strict-own")
    report = run(old, new)
    assert view(report, "wiki")["causes"] == ["data"]
    assert view(report, "strict")["causes"] == [] and view(report, "strict")["flag"] == "solver-diff"  # (a wiki item is not in the strict pool)


def test_a_community_entry_explains_a_strict_pick_and_not_a_wiki_one(tmp_path):
    old, new = pair(tmp_path)
    add_invented_item(old, "w91001", strict=False)
    add_invented_item(new, "w91001", strict=True)
    pick(new, "w91001")
    pick(new, "w91001", name="strict-own")
    report = run(old, new)
    assert view(report, "strict")["causes"] == ["community"]
    assert view(report, "wiki")["causes"] == [] and view(report, "wiki")["flag"] == "solver-diff"


@pytest.mark.parametrize("shard_name", ["wiki-own", "strict-own"])
@pytest.mark.parametrize(("flags", "zone"), LIFTS)
def test_an_item_a_report_lifted_from_hidden_to_strict_explains_the_picks_of_both_pools_it_joins_with_both_causes(tmp_path, flags, zone, shard_name):
    """Hidden to strict is in neither pool before and in both after: the rule of the pools credits the data (what let the report through) and the community (what makes the item
    strict) in each, and a pick of a pool the item does not join would be credited to neither."""
    old, new = pair(tmp_path)
    put_ladder_evidence(old, flags, reported=True, zone=zone)
    put_ladder_evidence(new, [], reported=True)
    pick(new, LADDER_ITEM, name=shard_name)
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == ["data", "community"] and change["flag"] is None


@pytest.mark.parametrize("shard_name", ["wiki-own", "strict-own"])
def test_an_item_a_mark_takes_from_strict_to_hidden_explains_the_picks_of_both_pools_it_leaves_with_the_data_alone(tmp_path, shard_name):
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [], reported=True)
    put_ladder_evidence(new, ["wiki_banner_dne"], reported=True)
    pick(old, LADDER_ITEM, name=shard_name)
    (change,) = of_kind(run(old, new), "scenario")
    assert change["causes"] == ["data"] and change["flag"] is None  # (the entry did not change)


@pytest.mark.parametrize("shard_name", ["wiki-own", "strict-own"])
def test_an_item_a_retraction_takes_from_strict_to_wiki_explains_the_strict_pick_alone_with_the_community(tmp_path, shard_name):
    old, new = pair(tmp_path)
    put_ladder_evidence(old, [], reported=True)
    put_ladder_evidence(new, [], reported=False, retracted=True)
    pick(old, LADDER_ITEM, name=shard_name)
    (change,) = of_kind(run(old, new), "scenario")
    if shard_name == "strict-own":
        assert change["causes"] == ["community"] and change["flag"] is None
    else:  # (the wiki pool held the item before and after: the pick moved for another reason, and a solver diff must not be hidden behind the retraction)
        assert change["causes"] == [] and change["flag"] == "solver-diff"


# ---- the runner-ups of a view that one release lacks, and the evidence of a view ------------------------------------------------------------------


def drop_view(doc, tier: int, race: str) -> None:
    doc["views"] = [v for v in doc["views"] if not (v[0] == tier and v[1] == race)]


def test_a_runner_up_view_that_one_release_lacks_is_added_or_removed(tmp_path):
    old, new = pair(tmp_path)
    edit_runnerups(new, "balanced", lambda doc: drop_view(doc, 4, "TRL"))
    (removed,) = of_kind(run(old, new), "runner-up")
    assert (removed["role"], removed["tier"], removed["race"], removed["change"]) == ("balanced", 4, "TRL", "removed")
    assert removed["fields"] == ["view"] and removed["causes"] == [] and removed["flag"] == "solver-diff"
    (added,) = of_kind(run(new, old), "runner-up")
    assert (added["race"], added["change"]) == ("TRL", "added")


def test_the_evidence_of_a_runner_up_view_is_compared_with_its_setup_and_its_swaps(tmp_path):
    old, new = pair(tmp_path)
    before = load(old / SLUG / "runnerups" / "balanced.json")["evidence"]
    other = "wiki" if before == "strict" else "strict"
    edit_runnerups(new, "balanced", lambda doc: doc.update(evidence=other))
    report = run(old, new)
    changes = of_kind(report, "runner-up")
    assert len(changes) == 9 and all(c["fields"] == ["evidence"] and c["evidence"] == [before, other] and c["flag"] == "solver-diff" for c in changes)


def test_a_view_that_is_added_in_a_tier_both_releases_have_is_not_missed_among_the_views_both_have(tmp_path):
    old, new = pair(tmp_path)
    edit_runnerups(new, "balanced", lambda doc: drop_view(doc, 0, "ELF"))
    edit_runnerups(new, "balanced", lambda doc: runnerup_place(doc, 4, "TRL", "HEAD", [(OTHER_ITEM, -3.0)]))
    kinds = sorted((c["race"], c["tier"], c["change"], tuple(c["fields"])) for c in of_kind(run(old, new), "runner-up"))
    assert kinds == [("ELF", 0, "removed", ("view",)), ("TRL", 4, "changed", ("places",))]


# ---- the whole default selection --------------------------------------------------------------------------------------------------------------


def test_the_view_the_default_is_made_at_is_compared(tmp_path):
    old, new = pair(tmp_path)
    edit(new / SLUG / "defaults.json", lambda d: d["view"].update(buffs="group"))
    (change,) = of_kind(run(old, new), "default")
    assert "view" in change["fields"] and change["flag"] == "solver-diff"
    old, new = pair(tmp_path / "evidence")
    other = "wiki" if load(old / SLUG / "defaults.json")["view"]["evidence"] == "strict" else "strict"
    edit(new / SLUG / "defaults.json", lambda d: d["view"].update(evidence=other))
    (change,) = of_kind(run(old, new), "default")
    assert "view" in change["fields"]


def test_a_default_that_one_release_lacks_is_added_or_removed(tmp_path):
    old, new = pair(tmp_path)
    (new / SLUG / "defaults.json").unlink()
    (removed,) = of_kind(run(old, new), "default")
    assert removed["change"] == "removed" and removed["fields"] == ["default"] and removed["flag"] == "solver-diff"
    (added,) = of_kind(run(new, old), "default")
    assert added["change"] == "added"


# ---- the gain of a scenario, and an item row that differs in a later shard -------------------------------------------------------------------------


def test_a_change_of_the_gain_of_a_scenario_alone_is_a_change(tmp_path):
    old, new = pair(tmp_path)
    file = shard(new)
    row = file.row(*OGR)
    before = row[6]
    row[6] = round(before + 1.5, 2)
    file.save()
    (change,) = of_kind(run(old, new), "scenario")
    assert change["fields"] == ["gain"] and change["gain"] == [before, round(before + 1.5, 2)] and change["delta"] == 0.0 and change["flag"] == "solver-diff"


COMMON_ITEM = "w80113"  # an item that all four shards of the fixture show, with the same row


def test_an_item_row_that_differs_in_a_later_shard_is_compared(tmp_path):
    old, new = pair(tmp_path)
    file = shard(new, "wiki-group")  # the last of the four: the first one that shows the item is strict-own
    file.doc["items"][file.item_index(COMMON_ITEM)][5] = "Quest in Another Zone"
    file.save()
    (record,) = of_kind(run(old, new), "item", key=COMMON_ITEM)
    assert "source" in record["fields"] and record["causes"] == ["data"]


def test_an_item_row_that_differs_in_the_first_trio_is_not_lost_to_the_row_of_a_later_one(tmp_path):
    old, new = pair(tmp_path)
    copy_trio(old, "war-clr-pal")
    copy_trio(new, "war-clr-pal")
    file = ShardFile(new / SLUG / "strict-own.json")  # the first trio, sorted by name: the later one has the old row, and used to overwrite it
    file.doc["items"][file.item_index(COMMON_ITEM)][5] = "Quest in Another Zone"
    file.save()
    later = ShardFile(new / "war-clr-pal" / "wiki-own.json")  # (a change in the later trio, so that it is read as well)
    row = later.row(*OGR)
    later.set_value(row, row[5] + 2.0)
    later.save()
    (record,) = of_kind(run(old, new), "item", key=COMMON_ITEM)
    assert "source" in record["fields"]


# ---- a bundle: what explains it depends on where it differs ---------------------------------------------------------------------------------------


def set_bundle_inputs(folder: Path) -> None:
    edit(folder / SLUG / "engine-l50.json", lambda b: b.update(inputs="ab" * 32))


def test_a_bundle_that_differs_outside_its_inputs_is_not_explained_by_a_change_of_source_text(tmp_path):
    """The source text of an item is shown by the shards and is no input of a bundle: a bundle that changed elsewhere than in its inputs field is a solver diff."""
    old, new = pair(tmp_path)
    file = shard(new, "wiki-group")
    file.doc["items"][file.item_index(COMMON_ITEM)][5] = "Quest in Another Zone"
    file.save()
    set_bundle(new)
    report = run(old, new)
    (change,) = of_kind(report, "bundle")
    assert change["causes"] == [] and change["flag"] == "solver-diff"
    assert of_kind(report, "item", key=COMMON_ITEM)  # (the change of text itself is reported)


@pytest.mark.parametrize(
    "apply",
    [
        lambda folder: change_item(folder),
        lambda folder: change_release_json(folder, catalog_sha256="7e" * 32),
        lambda folder: change_release_json(folder, catalog_date="2026-10-15"),
    ],
    ids=["a record of an item", "the catalog file", "the snapshot of the catalog"],
)
def test_a_bundle_that_differs_in_its_inputs_alone_is_explained_by_any_input_change(tmp_path, apply):
    old, new = pair(tmp_path)
    apply(new)
    set_bundle_inputs(new)
    (change,) = of_kind(run(old, new), "bundle")
    assert change["causes"] == ["data"] and change["flag"] is None


def test_a_bundle_that_differs_in_its_inputs_alone_with_no_input_changed_is_a_solver_diff(tmp_path):
    old, new = pair(tmp_path)
    set_bundle_inputs(new)
    (change,) = of_kind(run(old, new), "bundle")
    assert change["causes"] == [] and change["flag"] == "solver-diff"
