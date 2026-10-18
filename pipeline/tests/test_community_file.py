"""Tests for the format of ``rules/community-seen.json``: the reports that players made and a maintainer accepted.

The file is ``{"version", "reports": [{"key", "kind", "issue", "date", "check"}], "retracted": [{"key", "issue", "date", "reason"}]}``. It holds no free text and no
link: ``kind``, ``check`` and ``reason`` come from fixed lists, the issue is a number (the address of the issue is built from the owner of the build, see
``test_community_command.py``), and the date is a calendar day. The catalog builder reads it strictly with ``load_community_keys`` and takes the keys of ``reports`` only.
Every key and every address here is invented.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trioforge import community
from trioforge.data.catalog import BuildError, load_community_keys

REPO = Path(__file__).resolve().parents[2]
DATE = "2026-10-18"
SENTINEL = "Zorblax Sentinel"  # a made-up phrase: a refusal must never repeat what the file says


@pytest.fixture(autouse=True)
def today(monkeypatch):
    """The reader refuses a day after today (UTC). The day is fixed here, so that no test below depends on the clock."""
    monkeypatch.setattr(community, "today_utc", lambda: DATE)
    return DATE


def report(**over):
    entry = {"key": "w910001", "kind": "seen", "issue": 5, "date": DATE, "check": "item-window-screenshot"}
    entry.update(over)
    return entry


def retracted(**over):
    entry = {"key": "w910002", "issue": 7, "date": DATE, "reason": "withdrawn"}
    entry.update(over)
    return entry


def document(reports=None, retractions=None, **over):
    doc = {"version": DATE, "reports": [report()] if reports is None else reports, "retracted": [] if retractions is None else retractions}
    doc.update(over)
    return doc


def written(tmp_path, doc) -> Path:
    path = tmp_path / "community-seen.json"
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return path


def refusal(tmp_path, doc) -> str:
    with pytest.raises(BuildError) as caught:
        load_community_keys(written(tmp_path, doc))
    message = str(caught.value)
    assert message and "\n" not in message and SENTINEL not in message  # one line, and never what the file says
    return message


# ---- what is read ---------------------------------------------------------------------------------------------------------------------


def test_the_keys_of_the_reports_are_the_community_keys(tmp_path):
    doc = document([report(), report(key="w910003", kind="tier", issue=6)])
    assert load_community_keys(written(tmp_path, doc)) == frozenset({"w910001", "w910003"})


def test_an_empty_list_of_reports_gives_no_key(tmp_path):
    assert load_community_keys(written(tmp_path, document([]))) == frozenset()


def test_a_retracted_entry_gives_no_key_unless_another_report_still_holds_the_item(tmp_path):
    doc = document([report(), report(key="w910004", issue=9)], [retracted(), retracted(key="w910001", issue=4)])
    keys = load_community_keys(written(tmp_path, doc))
    assert keys == frozenset({"w910001", "w910004"})  # w910002 is retracted and has no other report; w910001 has issue 5 as well


def test_the_same_item_in_two_issues_is_one_key(tmp_path):
    doc = document([report(), report(issue=6)])
    assert load_community_keys(written(tmp_path, doc)) == frozenset({"w910001"})


def test_the_order_of_the_entries_does_not_matter_to_the_reader(tmp_path):
    doc = document([report(key="w910009", issue=9), report(key="w910001", issue=5)])
    assert load_community_keys(written(tmp_path, doc)) == frozenset({"w910001", "w910009"})


@pytest.mark.parametrize("key", ["rzorblax-ring", "r1", "rabc", "r" + "a" * 99, "r" + "a" * 100])
def test_only_the_key_of_a_wiki_page_is_a_key_of_a_report(tmp_path, key):
    """The public catalog has no item without a wiki page, and a slug of a hundred letters is a field that could hold a sentence: only w and a number is a key."""
    refusal(tmp_path, document([report(key=key)]))
    refusal(tmp_path, document(retractions=[retracted(key=key)]))


def test_the_longest_number_of_a_wiki_page_is_a_key(tmp_path):
    assert load_community_keys(written(tmp_path, document([report(key="w" + "9" * 15)]))) == frozenset({"w" + "9" * 15})


# ---- a day after today -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tomorrow", ["2026-10-19", "2027-01-01", "2126-10-18"])
def test_a_report_or_a_retraction_dated_after_today_is_refused(tmp_path, tomorrow):
    refusal(tmp_path, document([report(date=tomorrow)]))
    refusal(tmp_path, document(retractions=[retracted(date=tomorrow)]))
    refusal(tmp_path, document(version=tomorrow))


def test_a_report_dated_today_or_before_is_read(tmp_path, today):
    assert load_community_keys(written(tmp_path, document([report(date=today), report(key="w910003", issue=6, date="2026-01-01")], version=today))) == frozenset({"w910001", "w910003"})


def test_the_day_after_which_a_date_is_refused_is_the_utc_day_of_the_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(community, "today_utc", lambda: "2026-10-19")
    assert load_community_keys(written(tmp_path, document([report(date="2026-10-19")], version="2026-10-19"))) == frozenset({"w910001"})
    monkeypatch.setattr(community, "today_utc", lambda: "2026-10-17")
    refusal(tmp_path, document([report(date="2026-10-19")], version="2026-10-17"))


# ---- what is refused ------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param([], id="a list"),
        pytest.param("reports", id="a text"),
        pytest.param({}, id="an empty object"),
        pytest.param({"version": DATE, "reports": []}, id="no retracted list"),
        pytest.param({"version": DATE, "retracted": []}, id="no reports list"),
        pytest.param({"reports": [], "retracted": []}, id="no version"),
        pytest.param(document(note=SENTINEL), id="a field of the file that is not allowed"),
        pytest.param(document(**{SENTINEL: 1}), id="a field of the file with a made-up name"),
        pytest.param(document(version="2026-13-01"), id="a version that is no day"),
        pytest.param(document(version=20261018), id="a version that is a number"),
        pytest.param(document(version=DATE + "T00:00:00Z"), id="a version with a time"),
        pytest.param(document(reports="w910001"), id="reports that is a text"),
        pytest.param(document(reports={"key": "w910001"}), id="reports that is an object"),
        pytest.param(document(retractions="w910001"), id="retracted that is a text"),
        pytest.param(document(retractions={}), id="retracted that is an object"),
        pytest.param(document(["w910001"]), id="a report that is a text"),
        pytest.param(document([[]]), id="a report that is a list"),
        pytest.param(document(retractions=["w910001"]), id="a retracted entry that is a text"),
    ],
)
def test_a_file_that_is_not_the_form_is_refused(tmp_path, doc):
    refusal(tmp_path, doc)


@pytest.mark.parametrize("field", ["key", "kind", "issue", "date", "check"])
def test_a_report_without_one_of_its_fields_is_refused(tmp_path, field):
    entry = report()
    del entry[field]
    refusal(tmp_path, document([entry]))


@pytest.mark.parametrize("extra", ["note", "url", "player", "text", "reason", SENTINEL])
def test_a_report_with_a_field_that_is_not_allowed_is_refused_free_text_included(tmp_path, extra):
    refusal(tmp_path, document([report(**{extra: SENTINEL})]))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("key", "bad key"), ("key", "W910001"), ("key", "w"), ("key", "w91x"), ("key", "910001"), ("key", ""), ("key", 910001), ("key", None), ("key", "w" + "9" * 16),
        ("key", "r"), ("key", "rBad"), ("key", "w910001\n"), ("key", SENTINEL),
        ("kind", "other"), ("kind", "SEEN"), ("kind", "seen "), ("kind", ""), ("kind", None), ("kind", 1), ("kind", ["seen"]), ("kind", SENTINEL),
        ("issue", 0), ("issue", -1), ("issue", 1.0), ("issue", 5.5), ("issue", "5"), ("issue", None), ("issue", True), ("issue", 10**10), ("issue", [5]),
        ("issue", "https://example.invalid/issues/5"),
        ("date", "2026-02-30"), ("date", "2026-1-1"), ("date", "18 Oct 2026"), ("date", 20261018), ("date", ""), ("date", None), ("date", DATE + "T00:00:00Z"), ("date", SENTINEL),
        ("check", "other"), ("check", "screenshot"), ("check", ""), ("check", None), ("check", ["item-window-screenshot"]), ("check", SENTINEL),
    ],
)
def test_a_report_with_a_value_that_is_not_allowed_is_refused(tmp_path, field, value):
    refusal(tmp_path, document([report(**{field: value})]))


@pytest.mark.parametrize("field", ["key", "issue", "date", "reason"])
def test_a_retracted_entry_without_one_of_its_fields_is_refused(tmp_path, field):
    entry = retracted()
    del entry[field]
    refusal(tmp_path, document(retractions=[entry]))


@pytest.mark.parametrize("extra", ["note", "kind", "check", "url", SENTINEL])
def test_a_retracted_entry_with_a_field_that_is_not_allowed_is_refused(tmp_path, extra):
    refusal(tmp_path, document(retractions=[retracted(**{extra: SENTINEL})]))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("key", "bad key"), ("key", 5), ("issue", 0), ("issue", "7"), ("issue", True), ("date", "2026-02-30"), ("date", 7),
        ("reason", "other"), ("reason", "Withdrawn"), ("reason", ""), ("reason", None), ("reason", 3), ("reason", SENTINEL), ("reason", "mistake"),
        ("reason", "abuse"),  # (the first form of the list had it: beside an issue number it labelled the account of the reporter, publicly and for good)
    ],
)
def test_a_retracted_entry_with_a_value_that_is_not_allowed_is_refused(tmp_path, field, value):
    refusal(tmp_path, document(retractions=[retracted(**{field: value})]))


@pytest.mark.parametrize("reason", ["withdrawn", "wrong-item", "rejected", "duplicate"])
def test_each_reason_of_the_list_is_read(tmp_path, reason):
    assert load_community_keys(written(tmp_path, document(retractions=[retracted(reason=reason)]))) == frozenset({"w910001"})


@pytest.mark.parametrize("kind", ["seen", "tier"])
def test_each_kind_of_the_list_is_read(tmp_path, kind):
    assert load_community_keys(written(tmp_path, document([report(kind=kind)]))) == frozenset({"w910001"})


def test_the_same_report_twice_is_refused(tmp_path):
    refusal(tmp_path, document([report(), report(kind="tier", date="2026-10-19")]))  # (the same item and the same issue, whatever else differs)


def test_the_same_retracted_entry_twice_is_refused(tmp_path):
    refusal(tmp_path, document(retractions=[retracted(), retracted(reason="rejected")]))


def test_an_item_and_an_issue_both_reported_and_retracted_is_refused(tmp_path):
    refusal(tmp_path, document([report()], [retracted(key="w910001", issue=5)]))


def test_an_issue_in_both_lists_is_refused_whatever_the_items_are(tmp_path):
    """A retraction moves every entry of an issue, and a retracted issue takes no new report: an issue with entries in both lists is a file nobody made with the command."""
    refusal(tmp_path, document([report(key="w910001", issue=5)], [retracted(key="w910002", issue=5)]))
    refusal(tmp_path, document([report(key="w910001", issue=5), report(key="w910003", issue=6)], [retracted(key="w910004", issue=6)]))


def test_an_issue_with_several_entries_in_one_list_is_read(tmp_path):
    keys = load_community_keys(written(tmp_path, document([report(key="w910001", issue=5), report(key="w910002", issue=5)], [retracted(key="w910003", issue=7), retracted(key="w910004", issue=7)])))
    assert keys == frozenset({"w910001", "w910002"})


@pytest.mark.parametrize(
    "text",
    [
        pytest.param('{"version": "2026-10-18", "reports": [], "retracted": [], "reports": []}', id="a repeated field"),
        pytest.param('{"version": "2026-10-18", "reports": [', id="a file cut short"),
        pytest.param("", id="an empty file"),
        pytest.param('{"version": "2026-10-18", "reports": [{"key": "w910001", "kind": "seen", "issue": NaN, "date": "2026-10-18", "check": "item-window-screenshot"}], "retracted": []}', id="NaN"),
        pytest.param("﻿" + json.dumps(document()), id="a byte order mark"),
    ],
)
def test_a_file_that_is_not_strict_json_is_refused(tmp_path, text):
    refusal(tmp_path, text)


def test_a_file_that_is_not_utf8_is_refused(tmp_path):
    path = tmp_path / "community-seen.json"
    path.write_bytes(b'{"version": "2026-10-18", "reports": [], "retracted": [], "x": "\xff"}')
    with pytest.raises(BuildError):
        load_community_keys(path)


# ---- the file of the old form ---------------------------------------------------------------------------------------------------------

OLD = {"version": DATE, "reports": [{"key": "w910001", "issue": "https://example.invalid/issues/1"}]}


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param(OLD, id="a link for the issue, no kind, date or check, no retracted list"),
        pytest.param({"reports": OLD["reports"]}, id="no version either"),
        pytest.param({**OLD, "retracted": []}, id="a link for the issue, whatever else the file has"),
        pytest.param(document([report(issue="https://example.invalid/issues/5")]), id="a new report with a link for its issue"),
        pytest.param({"version": DATE, "reports": [{"key": "w910001"}]}, id="reports of the old form with no issue"),
    ],
)
def test_a_file_of_the_old_form_is_refused_with_the_line_that_says_how_to_convert_it(tmp_path, doc):
    message = refusal(tmp_path, doc)
    assert "old form" in message and "convert" in message and "community-seen.json" in message
    for word in ("kind", "issue", "date", "check", "retracted"):
        assert word in message  # the line names the fields the new form has
    assert "screenshot" in message  # and says that a report is kept only when a maintainer has checked one


def test_a_damaged_file_of_the_new_form_is_not_told_to_convert(tmp_path):
    assert "old form" not in refusal(tmp_path, document([report(kind="other")]))


# ---- the file of the repository -------------------------------------------------------------------------------------------------------


def test_the_file_of_the_repository_if_there_is_one_is_in_the_new_form():
    path = REPO / "rules" / "community-seen.json"
    if path.exists():
        load_community_keys(path)
