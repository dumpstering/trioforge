"""Tests for the eqlwiki fetcher: category listing, page batches and the fetch / record commands.

No network: a fake api.php (``FakeWiki``) answers through the polite client's fake transport,
and a fake clock records when each request started. All page and item names are invented.
"""

import gzip
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
from datetime import date
from pathlib import Path

import pytest

from trioforge.sources import eqlwiki
from trioforge.sources.eqlwiki import fetch_pages, list_category, page_records
from trioforge.sources.http import FetchError, PoliteClient

UA = "TrioForge-extractor/0.1 (+https://github.com/dumpstering/trioforge; non-commercial fan project; 1 request/s)"
DEFAULT_LOCK_PATH = eqlwiki.LOCK_PATH  # read at import, before the fixture below replaces it


@pytest.fixture(autouse=True)
def private_lock_file(tmp_path_factory, monkeypatch):
    """Every test runs with a lock file of its own, never the repository's sources/.eqlwiki.lock."""
    path = tmp_path_factory.mktemp("fetchlock") / ".eqlwiki.lock"
    monkeypatch.setattr(eqlwiki, "LOCK_PATH", path)
    return path


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeWiki:
    """A tiny api.php: list=categorymembers (paged) and prop=revisions by page id or title."""

    def __init__(
        self,
        member_count=120,
        gone=(),
        page_size=500,
        fail_after=None,
        interrupt_after=None,
        category="Category:Items",
    ):
        self.time = FakeTime()
        self.category = category
        self.members = [
            {"pageid": 1000 + n, "ns": 0, "title": f"Zorblax Item {n:03d}"} for n in range(member_count)
        ]
        self.gone = set(gone)  # listed in the category, but no longer on the wiki
        self.page_size = page_size
        self.fail_after = fail_after  # after this many requests, every request fails
        self.interrupt_after = interrupt_after  # after this many requests, Ctrl-C
        self.requests = []  # the parsed query of every request
        self.starts = []  # when each request started
        self.extra_pages = {}  # title -> api page object (for the record command)

    def client(self):
        return PoliteClient(UA, transport=self, clock=self.time.clock, sleep=self.time.sleep, honour_robots=False)

    def __call__(self, url, headers):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.requests.append(query)
        self.starts.append(self.time.now)
        assert len(self.requests) < 200, "runaway: the client keeps asking"
        if self.interrupt_after is not None and len(self.requests) > self.interrupt_after:
            raise KeyboardInterrupt
        if self.fail_after is not None and len(self.requests) > self.fail_after:
            raise urllib.error.URLError("network is down")
        assert query["format"] == "json" and query["formatversion"] == "2" and query["maxlag"] == "5"
        if query.get("list") == "categorymembers":
            body = self._members(query)
        elif query.get("prop") == "revisions":
            body = self._pages(query)
        else:
            raise AssertionError(f"unexpected request {query}")
        return 200, {}, json.dumps(body).encode("utf-8")

    def _members(self, query):
        assert query["action"] == "query"
        assert query["cmtitle"] == self.category
        assert query["cmtype"] == "page"
        assert query["cmnamespace"] == "0"
        assert query["cmlimit"] == "500"
        start = int(query.get("cmcontinue", "0"))
        if start:
            assert query["continue"] == "-||"
        limit = min(int(query["cmlimit"]), self.page_size)
        body = {
            "batchcomplete": True,
            "query": {"categorymembers": self.members[start : start + limit]},
        }
        if start + limit < len(self.members):
            body["continue"] = {"cmcontinue": str(start + limit), "continue": "-||"}
        return body

    def api_page(self, member):
        pageid = member["pageid"]
        return {
            "pageid": pageid,
            "ns": member["ns"],
            "title": member["title"],
            "revisions": [
                {
                    "revid": pageid * 10,
                    "parentid": pageid * 10 - 1,
                    "timestamp": "2026-10-01T12:00:00Z",
                    "slots": {
                        "main": {
                            "contentmodel": "wikitext",
                            "contentformat": "text/x-wiki",
                            "content": "{{Itempage|itemname=" + member["title"] + "|statsblock=Slot: EAR}}",
                        }
                    },
                }
            ],
        }

    def _pages(self, query):
        assert query["action"] == "query"
        assert query["rvprop"] == "ids|timestamp|content"
        assert query["rvslots"] == "main"
        by_id = {member["pageid"]: member for member in self.members}
        pages = []
        if "pageids" in query:
            ids = [int(part) for part in query["pageids"].split("|")]
            assert len(ids) <= 50
            for pageid in ids:
                if pageid in self.gone or pageid not in by_id:
                    pages.append({"pageid": pageid, "missing": True})
                else:
                    pages.append(self.api_page(by_id[pageid]))
        else:
            for title in query["titles"].split("|"):
                pages.append(self.extra_pages.get(title) or {"ns": 0, "title": title, "missing": True})
        return {"batchcomplete": True, "query": {"pages": pages}}

    @property
    def revision_requests(self):
        return [q for q in self.requests if q.get("prop") == "revisions"]

    @property
    def category_requests(self):
        return [q for q in self.requests if q.get("list") == "categorymembers"]


def run_cli(wiki, *args):
    return eqlwiki.main(list(args), client=wiki.client(), today=date(2026, 10, 14))


def tree(directory):
    """Every file under directory as {relative path: bytes}."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def read_batch(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


# ---- the constant ---------------------------------------------------------------------------


def test_the_user_agent_constant_is_exactly_the_agreed_string():
    assert eqlwiki.USER_AGENT == UA


# ---- (g) list_category ----------------------------------------------------------------------


def test_list_category_follows_two_continue_pages_and_keeps_order():
    wiki = FakeWiki(member_count=3, page_size=1)
    members = list_category(wiki.client(), "Category:Items")
    assert members == [
        {"pageid": 1000, "title": "Zorblax Item 000"},
        {"pageid": 1001, "title": "Zorblax Item 001"},
        {"pageid": 1002, "title": "Zorblax Item 002"},
    ]
    assert len(wiki.category_requests) == 3
    first, second, third = wiki.category_requests
    assert "cmcontinue" not in first
    assert (second["cmcontinue"], second["continue"]) == ("1", "-||")
    assert (third["cmcontinue"], third["continue"]) == ("2", "-||")
    assert all(q["list"] == "categorymembers" for q in wiki.category_requests)


def test_list_category_keeps_the_first_of_a_page_that_two_continue_pages_both_give():
    """The sort key of a page can move across the cursor while a category of some twenty pages of the listing is read, so the page comes on two of them."""
    wiki = FakeWiki(member_count=4, page_size=2)
    first, second, third, fourth = wiki.members
    wiki.members = [first, second, {**second, "title": "Zorblax Item 001 renamed"}, third]  # the second page of the listing starts with the last of the first
    members = list_category(wiki.client(), "Category:Items")
    assert members == [
        {"pageid": first["pageid"], "title": first["title"]},
        {"pageid": second["pageid"], "title": second["title"]},  # (the first of the two: the one that was listed in its turn)
        {"pageid": third["pageid"], "title": third["title"]},
    ]
    assert len(wiki.category_requests) == 2


def test_list_category_keeps_the_order_and_every_page_when_none_comes_twice():
    wiki = FakeWiki(member_count=5, page_size=2)
    assert [member["pageid"] for member in list_category(wiki.client(), "Category:Items")] == [1000, 1001, 1002, 1003, 1004]


def test_list_category_asks_for_main_namespace_pages_only():
    wiki = FakeWiki(member_count=2)
    list_category(wiki.client(), "Category:Items")
    (query,) = wiki.category_requests
    assert query["cmtype"] == "page"
    assert query["cmnamespace"] == "0"
    assert query["cmlimit"] == "500"
    assert query["cmtitle"] == "Category:Items"


def test_list_category_of_an_empty_category_is_an_empty_list():
    assert list_category(FakeWiki(member_count=0).client(), "Category:Items") == []


# ---- (h) fetch_pages ------------------------------------------------------------------------


def test_fetch_pages_splits_120_ids_into_50_50_20_and_marks_missing_pages():
    wiki = FakeWiki(member_count=120, gone={1003, 1119})
    ids = [member["pageid"] for member in wiki.members]
    records = list(fetch_pages(wiki.client(), ids))
    sizes = [len(q["pageids"].split("|")) for q in wiki.revision_requests]
    assert sizes == [50, 50, 20]
    assert [r["pageid"] for r in records] == ids  # one record per id, in the order asked
    missing = [r for r in records if r.get("missing")]
    assert [r["pageid"] for r in missing] == [1003, 1119]
    assert all(r["content"] is None and r["revid"] is None for r in missing)
    found = records[0]
    assert found == {
        "pageid": 1000,
        "ns": 0,
        "title": "Zorblax Item 000",
        "revid": 10000,
        "timestamp": "2026-10-01T12:00:00Z",
        "content": "{{Itempage|itemname=Zorblax Item 000|statsblock=Slot: EAR}}",
    }
    assert "missing" not in found


def test_fetch_pages_yields_lazily_one_batch_at_a_time():
    wiki = FakeWiki(member_count=120)
    stream = fetch_pages(wiki.client(), [m["pageid"] for m in wiki.members])
    assert wiki.requests == []  # a generator: nothing is asked until it is iterated
    next(stream)
    assert len(wiki.revision_requests) == 1


def test_fetch_pages_asks_for_revision_ids_timestamps_and_main_slot_content():
    wiki = FakeWiki(member_count=2)
    list(fetch_pages(wiki.client(), [1000, 1001]))
    (query,) = wiki.revision_requests
    assert query["prop"] == "revisions"
    assert query["rvprop"] == "ids|timestamp|content"
    assert query["rvslots"] == "main"
    assert query["pageids"] == "1000|1001"


def test_fetch_pages_marks_an_id_the_wiki_never_returned_as_missing():
    wiki = FakeWiki(member_count=1)
    records = list(fetch_pages(wiki.client(), [1000, 424242]))
    assert records[1]["pageid"] == 424242 and records[1]["missing"] is True


def test_fetch_pages_takes_batch_sizes_up_to_50_only():
    wiki = FakeWiki(member_count=3)
    with pytest.raises(ValueError):
        list(fetch_pages(wiki.client(), [1000], batch=51))
    with pytest.raises(ValueError):
        list(fetch_pages(wiki.client(), [1000], batch=0))
    assert [r["pageid"] for r in fetch_pages(wiki.client(), [1000, 1001, 1002], batch=2)] == [1000, 1001, 1002]
    assert [q["pageids"] for q in wiki.revision_requests] == ["1000|1001", "1002"]


def test_fetch_pages_follows_a_continuation_before_calling_anything_missing():
    wiki = FakeWiki(member_count=2)
    page_a, page_b = (wiki.api_page(m) for m in wiki.members)
    bare_b = {"pageid": page_b["pageid"], "ns": 0, "title": page_b["title"]}  # revisions deferred
    first = {"continue": {"rvcontinue": "20261001|9", "continue": "||"}, "query": {"pages": [page_a, bare_b]}}
    second = {"batchcomplete": True, "query": {"pages": [page_b]}}
    sent = []

    def transport(url, headers):
        sent.append(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)))
        return 200, {}, json.dumps(first if len(sent) == 1 else second).encode()

    client = PoliteClient(UA, transport=transport, clock=wiki.time.clock, sleep=wiki.time.sleep, honour_robots=False)
    records = list(fetch_pages(client, [1000, 1001]))
    assert [r.get("missing") for r in records] == [None, None]
    assert records[1]["content"].startswith("{{Itempage")
    assert (sent[1]["rvcontinue"], sent[1]["continue"]) == ("20261001|9", "||")


def test_page_records_reads_a_titles_response_like_the_fixtures():
    wiki = FakeWiki(member_count=1)
    response = {"batchcomplete": True, "query": {"pages": [wiki.api_page(wiki.members[0])]}}
    (record,) = page_records(response)
    assert record["title"] == "Zorblax Item 000" and record["revid"] == 10000 and record["ns"] == 0


def test_page_records_marks_missing_and_invalid_pages():
    response = {
        "query": {
            "pages": [
                {"ns": 0, "title": "Nothing Here", "missing": True},
                {"title": "Bad|Title", "invalidreason": "no", "invalid": True},
            ]
        }
    }
    records = page_records(response)
    assert [r["missing"] for r in records] == [True, True]
    assert records[0]["title"] == "Nothing Here" and records[0]["pageid"] is None


def test_page_records_gives_empty_content_when_the_main_slot_has_none():
    page = {
        "pageid": 7,
        "ns": 0,
        "title": "Hidden",
        "revisions": [{"revid": 70, "timestamp": "2026-10-01T00:00:00Z", "slots": {"main": {"texthidden": True}}}],
    }
    (record,) = page_records({"query": {"pages": [page]}})
    assert record["content"] == "" and "missing" not in record


# ---- (j) the fetch command: files and counts --------------------------------------------------


def test_fetch_writes_members_batches_and_a_manifest_with_the_right_counts(tmp_path):
    wiki = FakeWiki(member_count=120, gone={1003, 1119})
    out = tmp_path / "2026-10-13"
    assert run_cli(wiki, "fetch", "--out", str(out)) == 0
    files = sorted(path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file())
    assert files == [
        "manifest.json",
        "raw/batch-0000.json.gz",
        "raw/batch-0001.json.gz",
        "raw/batch-0002.json.gz",
        "raw/members.json",
    ]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "date": "2026-10-13",
        "category": "Category:Items",
        "members": 120,
        "batches": 3,
        "pages": 118,
        "missing": 2,
    }
    assert list(manifest) == ["date", "category", "members", "batches", "pages", "missing"]
    members = json.loads((out / "raw" / "members.json").read_text(encoding="utf-8"))
    assert members["category"] == "Category:Items"
    assert [m["pageid"] for m in members["members"]] == [1000 + n for n in range(120)]
    batch = read_batch(out / "raw" / "batch-0002.json.gz")
    assert batch["batch"] == 2
    assert batch["pageids"] == [1100 + n for n in range(20)]
    assert [p["pageid"] for p in batch["pages"]] == batch["pageids"]
    assert batch["pages"][19]["missing"] is True  # 1119


def test_batch_files_carry_no_timestamp_so_a_rerun_writes_the_same_bytes(tmp_path):
    wiki = FakeWiki(member_count=3)
    out = tmp_path / "2026-10-13"
    assert run_cli(wiki, "fetch", "--out", str(out)) == 0
    header = (out / "raw" / "batch-0000.json.gz").read_bytes()[:10]
    assert header[:2] == b"\x1f\x8b" and header[4:8] == b"\x00\x00\x00\x00"  # the gzip mtime field


def test_fetch_starts_every_request_at_least_a_second_after_the_last(tmp_path):
    wiki = FakeWiki(member_count=120)
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == 0
    gaps = [b - a for a, b in zip(wiki.starts, wiki.starts[1:])]
    assert len(wiki.starts) == 4 and all(gap >= 1.0 for gap in gaps)


def test_fetch_uses_the_category_option(tmp_path):
    wiki = FakeWiki(member_count=1, category="Category:Zorblax Spells")
    out = tmp_path / "2026-10-13"
    assert run_cli(wiki, "fetch", "--out", str(out), "--category", "Category:Zorblax Spells") == 0
    assert wiki.category_requests[0]["cmtitle"] == "Category:Zorblax Spells"
    assert json.loads((out / "manifest.json").read_text())["category"] == "Category:Zorblax Spells"


def test_fetch_defaults_to_category_items(tmp_path):
    wiki = FakeWiki(member_count=1)
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == 0
    assert wiki.category_requests[0]["cmtitle"] == "Category:Items"


def test_the_manifest_date_follows_the_directory_name_else_today(tmp_path):
    wiki = FakeWiki(member_count=1)
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == 0
    assert json.loads((tmp_path / "2026-10-13" / "manifest.json").read_text())["date"] == "2026-10-13"
    wiki = FakeWiki(member_count=1)
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "scratch")) == 0
    assert json.loads((tmp_path / "scratch" / "manifest.json").read_text())["date"] == "2026-10-14"


def test_fetch_prints_progress_every_ten_batches(tmp_path, capsys):
    wiki = FakeWiki(member_count=21 * 50 - 7)  # 21 batches
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == 0
    printed = capsys.readouterr().out
    assert "10/21" in printed and "20/21" in printed
    assert "5/21" not in printed and "15/21" not in printed
    assert "21 batches" in printed  # the closing summary


def test_fetch_of_an_empty_category_writes_an_empty_manifest(tmp_path):
    wiki = FakeWiki(member_count=0)
    out = tmp_path / "2026-10-13"
    assert run_cli(wiki, "fetch", "--out", str(out)) == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["members"], manifest["batches"], manifest["pages"], manifest["missing"]) == (0, 0, 0, 0)


# ---- (i) --resume ---------------------------------------------------------------------------


def clean_run(tmp_path, name="clean", **wiki_args):
    wiki = FakeWiki(**wiki_args)
    out = tmp_path / name / "2026-10-13"
    assert run_cli(wiki, "fetch", "--out", str(out)) == 0
    return out


def test_resume_with_batch_0_present_requests_only_the_later_batches(tmp_path):
    out = clean_run(tmp_path, member_count=120, gone={1003, 1119})
    clean = tree(out)
    (out / "manifest.json").unlink()
    (out / "raw" / "batch-0001.json.gz").unlink()
    (out / "raw" / "batch-0002.json.gz").unlink()

    wiki = FakeWiki(member_count=120, gone={1003, 1119})
    assert run_cli(wiki, "fetch", "--out", str(out), "--resume") == 0
    assert len(wiki.requests) == 2  # batches 1 and 2 only: no category listing, no batch 0
    assert wiki.category_requests == []
    assert [q["pageids"].split("|")[0] for q in wiki.revision_requests] == ["1050", "1100"]
    assert tree(out) == clean  # byte for byte what one clean run writes


def test_resume_after_a_network_drop_gives_the_same_output_as_a_clean_run(tmp_path):
    clean = tree(clean_run(tmp_path, member_count=170, gone={1060}))

    broken = FakeWiki(member_count=170, gone={1060}, fail_after=2)  # listing, batch 0, then the line drops
    out = tmp_path / "resumed" / "2026-10-13"
    assert run_cli(broken, "fetch", "--out", str(out)) == 2
    assert sorted(tree(out)) == ["raw/batch-0000.json.gz", "raw/members.json"]  # no manifest, no stray files

    healthy = FakeWiki(member_count=170, gone={1060})
    assert run_cli(healthy, "fetch", "--out", str(out), "--resume") == 0
    assert len(healthy.revision_requests) == 3  # batches 1, 2, 3 of 4
    assert tree(out) == clean


def test_resume_after_ctrl_c_gives_the_same_output_as_a_clean_run(tmp_path, capsys):
    clean = tree(clean_run(tmp_path, member_count=170))
    interrupted = FakeWiki(member_count=170, interrupt_after=3)  # listing, batch 0, batch 1, Ctrl-C
    out = tmp_path / "resumed" / "2026-10-13"
    assert run_cli(interrupted, "fetch", "--out", str(out)) == 130
    assert "--resume" in capsys.readouterr().err
    assert sorted(tree(out)) == ["raw/batch-0000.json.gz", "raw/batch-0001.json.gz", "raw/members.json"]
    healthy = FakeWiki(member_count=170)
    assert run_cli(healthy, "fetch", "--out", str(out), "--resume") == 0
    assert tree(out) == clean


def test_a_failed_run_tells_the_user_how_to_resume(tmp_path, capsys):
    wiki = FakeWiki(member_count=120, fail_after=0)
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == 2
    error = capsys.readouterr().err
    assert "--resume" in error and "eqlwiki.com" in error


def test_resume_refetches_a_batch_that_does_not_parse(tmp_path):
    out = clean_run(tmp_path, member_count=120)
    clean = tree(out)
    (out / "raw" / "batch-0001.json.gz").write_bytes(b"\x1f\x8b not really gzip")  # a torn write
    (out / "raw" / "batch-0002.json.gz").write_bytes(gzip.compress(b'{"batch": 2, "pag'))  # cut JSON
    wiki = FakeWiki(member_count=120)
    assert run_cli(wiki, "fetch", "--out", str(out), "--resume") == 0
    assert len(wiki.revision_requests) == 2
    assert tree(out) == clean


def test_resume_refetches_a_batch_that_holds_other_pages(tmp_path):
    out = clean_run(tmp_path, member_count=120)
    clean = tree(out)
    other = out.parent / "other" / "2026-10-13"
    assert run_cli(FakeWiki(member_count=60), "fetch", "--out", str(other)) == 0
    # Batch 1 of the 60-page run holds ten pages, not the fifty this category needs there.
    (out / "raw" / "batch-0001.json.gz").write_bytes((other / "raw" / "batch-0001.json.gz").read_bytes())
    wiki = FakeWiki(member_count=120)
    assert run_cli(wiki, "fetch", "--out", str(out), "--resume") == 0
    assert len(wiki.revision_requests) == 1
    assert tree(out) == clean


def test_resume_without_members_lists_the_category_again(tmp_path):
    out = clean_run(tmp_path, member_count=120)
    clean = tree(out)
    (out / "raw" / "members.json").unlink()
    (out / "manifest.json").unlink()
    wiki = FakeWiki(member_count=120)
    assert run_cli(wiki, "fetch", "--out", str(out), "--resume") == 0
    assert len(wiki.category_requests) == 1 and wiki.revision_requests == []  # all batches were fine
    assert tree(out) == clean


def test_resume_refuses_a_directory_holding_another_category(tmp_path, capsys):
    out = clean_run(tmp_path, member_count=60)
    wiki = FakeWiki(member_count=60)
    assert run_cli(wiki, "fetch", "--out", str(out), "--resume", "--category", "Category:Spells") == 2
    assert wiki.requests == []
    assert "Category:Items" in capsys.readouterr().err


def test_a_refused_resume_leaves_the_manifest_and_every_file_as_they_were(tmp_path):
    """The manifest was deleted before the category was checked, so a --resume with the wrong --category left a directory with no manifest, which the catalog build then refuses."""
    out = clean_run(tmp_path, member_count=60)
    before = tree(out)
    manifest = (out / "manifest.json").read_bytes()
    wiki = FakeWiki(member_count=60)
    assert run_cli(wiki, "fetch", "--out", str(out), "--resume", "--category", "Category:Spells") == 2
    assert wiki.requests == []
    assert (out / "manifest.json").read_bytes() == manifest and tree(out) == before


def test_a_resume_of_the_right_category_still_has_no_manifest_while_the_run_is_unfinished(tmp_path):
    out = clean_run(tmp_path, member_count=120)
    assert (out / "manifest.json").exists()
    wiki = FakeWiki(member_count=120, interrupt_after=0)  # a damaged batch is asked for again, and Ctrl-C comes at once
    (out / "raw" / "batch-0000.json.gz").write_bytes(b"garbage")
    assert run_cli(wiki, "fetch", "--out", str(out), "--resume") == 130
    assert not (out / "manifest.json").exists()


def test_a_run_without_resume_fetches_everything_again(tmp_path):
    out = clean_run(tmp_path, member_count=120)
    clean = tree(out)
    (out / "raw" / "batch-0001.json.gz").write_bytes(b"garbage")
    wiki = FakeWiki(member_count=120)
    assert run_cli(wiki, "fetch", "--out", str(out)) == 0
    assert len(wiki.category_requests) == 1 and len(wiki.revision_requests) == 3
    assert tree(out) == clean


def test_a_shrunken_category_leaves_no_stale_batch_files(tmp_path):
    out = clean_run(tmp_path, member_count=120)
    wiki = FakeWiki(member_count=60)
    assert run_cli(wiki, "fetch", "--out", str(out)) == 0
    assert sorted(p.name for p in (out / "raw").iterdir()) == [
        "batch-0000.json.gz",
        "batch-0001.json.gz",
        "members.json",
    ]
    assert json.loads((out / "manifest.json").read_text())["batches"] == 2


def test_resume_reuses_the_saved_members_even_if_the_wiki_has_changed(tmp_path):
    out = clean_run(tmp_path, member_count=120)
    clean = tree(out)
    (out / "raw" / "batch-0002.json.gz").unlink()
    (out / "manifest.json").unlink()
    grown = FakeWiki(member_count=130)  # ten pages were added to the category since
    assert run_cli(grown, "fetch", "--out", str(out), "--resume") == 0
    assert grown.category_requests == []
    assert tree(out) == clean  # the same partition as the first run, not a shifted one


# ---- the record command ---------------------------------------------------------------------


def test_record_saves_the_raw_response_of_each_title_one_request_each(tmp_path):
    wiki = FakeWiki(member_count=0)
    wiki.extra_pages["Zorblax's Ring"] = wiki.api_page({"pageid": 5, "ns": 0, "title": "Zorblax's Ring"})
    out = tmp_path / "wiki"
    assert run_cli(wiki, "record", "--out", str(out), "Zorblax's Ring", "Nothing Here") == 0
    assert [q["titles"] for q in wiki.requests] == ["Zorblax's Ring", "Nothing Here"]
    assert all("redirects" not in q for q in wiki.requests)  # a redirect page is recorded as itself
    assert wiki.starts[1] - wiki.starts[0] >= 1.0
    assert sorted(p.name for p in out.iterdir()) == ["nothing-here.json", "zorblaxs-ring.json"]
    saved = json.loads((out / "zorblaxs-ring.json").read_text(encoding="utf-8"))
    assert saved["query"]["pages"][0]["revisions"][0]["revid"] == 50
    gone = json.loads((out / "nothing-here.json").read_text(encoding="utf-8"))
    assert gone["query"]["pages"][0]["missing"] is True


def test_record_slugs_are_ascii_lowercase_words():
    assert eqlwiki.fixture_slug("Engineer's Ring") == "engineers-ring"
    assert eqlwiki.fixture_slug("Wu's Fist of Mastery") == "wus-fist-of-mastery"
    assert eqlwiki.fixture_slug("  Mask  of /Deception ") == "mask-of-deception"
    assert eqlwiki.fixture_slug("Ünï Ring") == "uni-ring"


def test_record_refuses_titles_with_no_usable_file_name_before_any_request(tmp_path):
    wiki = FakeWiki(member_count=0)
    with pytest.raises(SystemExit):
        run_cli(wiki, "record", "--out", str(tmp_path), "Zorblax Ring", "'''")
    assert wiki.requests == []


def test_record_refuses_two_titles_that_would_share_a_file(tmp_path):
    wiki = FakeWiki(member_count=0)
    with pytest.raises(SystemExit):
        run_cli(wiki, "record", "--out", str(tmp_path), "Zorblax Ring", "zorblax  ring")
    assert wiki.requests == []


def test_record_with_no_titles_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit):
        run_cli(FakeWiki(member_count=0), "record", "--out", str(tmp_path))


# ---- one run at a time ----------------------------------------------------------------------
# The wiki is asked for one request a second; two runs at once would ask for two. A lock file holding the
# process id of the running fetch keeps a second run out for as long as the first lives.


def dead_pid():
    """The process id of a process that has finished."""
    done = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True, check=True)
    return int(done.stdout)


class LockWatcher(FakeWiki):
    """A wiki that notes what the lock file held when the first request arrived."""

    def __init__(self, lock, **kwargs):
        super().__init__(**kwargs)
        self.lock = lock
        self.held = None

    def __call__(self, url, headers):
        if self.held is None:
            self.held = self.lock.read_text(encoding="ascii")
        return super().__call__(url, headers)


def test_the_default_lock_is_one_file_per_api_host_in_the_sources_folder():
    assert DEFAULT_LOCK_PATH == Path(__file__).resolve().parents[2] / "sources" / ".eqlwiki.lock"


def test_a_fetch_holds_a_lock_file_with_its_process_id_and_removes_it_when_done(private_lock_file):
    wiki = LockWatcher(private_lock_file, member_count=60)
    assert not private_lock_file.exists()
    assert run_cli(wiki, "fetch", "--out", str(private_lock_file.parent / "2026-10-13")) == 0
    assert wiki.held.strip() == str(os.getpid())
    assert not private_lock_file.exists()


def test_a_second_run_is_refused_while_the_first_holds_the_lock(private_lock_file, capsys):
    wiki = FakeWiki(member_count=60)
    out = private_lock_file.parent / "2026-10-13"
    with eqlwiki.FetchLock(private_lock_file):
        assert run_cli(wiki, "fetch", "--out", str(out)) == 2
        assert wiki.requests == []  # not one request, and nothing written
        assert not out.exists()
        assert "another fetch is running" in capsys.readouterr().err
        assert private_lock_file.exists()  # the refused run did not take the first one's lock away
    assert not private_lock_file.exists()
    assert run_cli(FakeWiki(member_count=60), "fetch", "--out", str(out)) == 0  # free again


def test_the_record_command_takes_the_lock_too(private_lock_file, tmp_path, capsys):
    wiki = FakeWiki(member_count=0)
    with eqlwiki.FetchLock(private_lock_file):
        assert run_cli(wiki, "record", "--out", str(tmp_path / "wiki"), "Zorblax Ring") == 2
    assert wiki.requests == [] and "another fetch is running" in capsys.readouterr().err
    assert run_cli(wiki, "record", "--out", str(tmp_path / "wiki"), "Zorblax Ring") == 0
    assert not private_lock_file.exists()


@pytest.mark.parametrize("how", ["failure", "ctrl-c"])
def test_the_lock_is_released_after_a_failed_or_interrupted_run(private_lock_file, tmp_path, how):
    wiki = FakeWiki(member_count=120, **({"fail_after": 1} if how == "failure" else {"interrupt_after": 1}))
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == (2 if how == "failure" else 130)
    assert not private_lock_file.exists()


def test_a_lock_left_by_a_process_that_died_is_taken_over(private_lock_file, tmp_path):
    private_lock_file.write_text(f"{dead_pid()}\n", encoding="ascii")
    wiki = LockWatcher(private_lock_file, member_count=60)
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == 0
    assert wiki.held.strip() == str(os.getpid())  # the new run's id, not the dead one's
    assert not private_lock_file.exists()


def test_a_lock_that_names_a_live_process_is_respected(private_lock_file, tmp_path, capsys):
    private_lock_file.write_text(f"{os.getpid()}\n", encoding="ascii")  # this very process is alive
    wiki = FakeWiki(member_count=60)
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == 2
    assert wiki.requests == []
    assert "another fetch is running" in capsys.readouterr().err
    assert private_lock_file.read_text(encoding="ascii").strip() == str(os.getpid())


def test_a_lock_file_that_is_no_process_id_blocks_a_fresh_run_but_not_an_old_one(private_lock_file, tmp_path, capsys):
    private_lock_file.write_text("no pid here", encoding="ascii")
    wiki = FakeWiki(member_count=60)
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == 2  # a run may be writing it right now
    assert wiki.requests == [] and "another fetch is running" in capsys.readouterr().err
    long_ago = time.time() - 3600
    os.utime(private_lock_file, (long_ago, long_ago))
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == 0  # nobody takes an hour to write a pid
    assert not private_lock_file.exists()


def test_a_lock_is_released_only_by_the_run_that_holds_it(private_lock_file):
    lock = eqlwiki.FetchLock(private_lock_file)
    lock.acquire()
    private_lock_file.write_text("999999999\n", encoding="ascii")  # somebody else took over after a mistake
    lock.release()
    assert private_lock_file.read_text(encoding="ascii").strip() == "999999999"
    private_lock_file.unlink()


def test_a_lock_can_be_taken_again_after_release_and_releasing_twice_is_harmless(private_lock_file):
    lock = eqlwiki.FetchLock(private_lock_file)
    lock.acquire()
    lock.release()
    lock.release()
    with eqlwiki.FetchLock(private_lock_file):
        assert private_lock_file.exists()


def test_the_lock_folder_is_made_when_it_is_missing(tmp_path):
    path = tmp_path / "not" / "yet" / ".eqlwiki.lock"
    with eqlwiki.FetchLock(path):
        assert path.is_file()
    assert not path.exists()


def test_pid_alive_knows_this_process_and_a_finished_one():
    assert eqlwiki._pid_alive(os.getpid()) is True
    assert eqlwiki._pid_alive(dead_pid()) is False
    assert eqlwiki._pid_alive(0) is False and eqlwiki._pid_alive(-5) is False


def test_the_liveness_check_never_signals_the_process(monkeypatch):
    # os.kill(pid, 0) would end the process on Windows: the check must not call it there
    calls = []
    monkeypatch.setattr(os, "kill", lambda *args: calls.append(args))
    eqlwiki._pid_alive(os.getpid())
    if os.name == "nt":
        assert calls == []


def test_temporary_files_are_unique_to_each_write(tmp_path, monkeypatch):
    names = []
    real_replace = os.replace

    def spy(source, target):
        names.append(Path(source).name)
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", spy)
    target = tmp_path / "batch-0000.json.gz"
    eqlwiki._atomic_write(target, b"one")
    eqlwiki._atomic_write(target, b"two")
    assert len(names) == 2 and names[0] != names[1]
    assert all(name.startswith("batch-0000.json.gz.") and name.endswith(".tmp") for name in names)
    assert str(os.getpid()) in names[0]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["batch-0000.json.gz"]  # no leftovers
    assert target.read_bytes() == b"two"


def test_a_failed_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    def broken(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        eqlwiki._atomic_write(tmp_path / "members.json", b"x")
    assert list(tmp_path.iterdir()) == []


class BusyWiki(FakeWiki):
    """Answers every request with 429 and the given Retry-After."""

    def __init__(self, retry_after, **kwargs):
        super().__init__(**kwargs)
        self.retry_after = retry_after

    def __call__(self, url, headers):
        self.requests.append(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)))
        return 429, {"Retry-After": self.retry_after}, b""


def test_a_retry_after_over_ten_minutes_stops_the_run_and_says_how_to_resume(tmp_path, capsys, private_lock_file):
    wiki = BusyWiki("86400")
    assert run_cli(wiki, "fetch", "--out", str(tmp_path / "2026-10-13")) == 2
    error = capsys.readouterr().err
    assert "server asked to wait too long" in error and "--resume" in error
    assert len(wiki.requests) == 1  # it did not come back early
    assert wiki.time.sleeps == []
    assert not private_lock_file.exists()


# ---- a wiki that never stops continuing -----------------------------------------------------


class StuckWiki(FakeWiki):
    """Answers every request with the same continuation token, as a broken wiki might."""

    def _members(self, query):
        body = super()._members(query)
        body["continue"] = {"cmcontinue": "stuck", "continue": "-||"}
        return body

    def _pages(self, query):
        body = super()._pages(query)
        body["continue"] = {"rvcontinue": "stuck", "continue": "||"}
        return body

    def __call__(self, url, headers):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if "cmcontinue" in query:
            assert query["cmcontinue"] == "stuck"
            query["cmcontinue"] = "0"  # let the fake serve the first page again
            url = url.split("?")[0] + "?" + urllib.parse.urlencode(query)
        return super().__call__(url, headers)


def test_list_category_gives_up_on_a_repeated_continuation_token():
    wiki = StuckWiki(member_count=3, page_size=1)
    with pytest.raises(FetchError):
        list_category(wiki.client(), "Category:Items")
    assert len(wiki.category_requests) == 2  # asked again once, then refused to loop


def test_fetch_pages_gives_up_on_a_repeated_continuation_token():
    wiki = StuckWiki(member_count=3)
    with pytest.raises(FetchError):
        list(fetch_pages(wiki.client(), [1000, 1001]))
    assert len(wiki.revision_requests) == 2


# ---- the recorded fixtures ------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "wiki"
FIXTURE_TITLES = [
    "Engineer's Ring",
    "Girdle of Faith",
    "Cloak of Flames",
    "Shield of the Stalwart Seas",
    "Bladestopper",
    "Earthshaker",
    "Wu's Fist of Mastery",
    "Torrid Corruptor",
    "Baton of the Sky",
    "Talisman of Kejaar Kerrath",
    "Skinner's Belt",
    "Imbued Granite Spaulders",
    "Darkwar Mask",
    "Rusty Dagger",
    "Bone Chips",
    "Backpack",
    "Mask of Deception",
    "Dwarven Chain Tunic",
    "Symbol of Marr",
    "Ethereal Mist Chestplate",
]
# Recorded later, for the crafting reader (see fixtures/wiki/README.md).
CRAFTING_FIXTURE_TITLES = [
    "Banded Belt",
    "Ogre Bouncer Shield",
    "Block of Adamantite",
    "Crystalline Silk Cloak",
    "Large Patchwork Cloak",
    "10 Dose Greater Null Potion",
    "Air Tight Box",
]
# Taken from the cached full pull of 2026-10-14 for the parser fixes (no new request; see fixtures/wiki/README.md).
PARSER_FIXTURE_TITLES = [
    "Azzar's Dreadful Hat",
    "Imbued Northman Long Dagger",
    "Kejekan Smithy Hammer",
    "Imbued Black Pearl Electrum Choker",
    "Blessed Champion Arrows",
    "Batling Eye",
    "10 Dose Adrenaline Tap",
    "A Crude Stein",
    "Serpent's Tooth",
    "Kerasian Axe of Ire",
    "Yelinak's Talisman",
    "Teir`Dal Adamantite Vambraces",
    "Velvet-Trimmed Satin Robe",
    "Tri-Plated Golden Hackle Hammer",
    "Azarack Skin Wristwraps",
    "Feir`Dal Fletching Kit",
    "A Bowyers Guide",
    "Spell: Aegolism",
    "Aerated Pauldrons",
    "Basoon Haste Gauntlets",
    "Bronze Ulak",
    "Crushbone Battle Beads",
    "Blackened Iron Armplates",
    "Robe of Discord",
    "Unadorned Breastplate",
]
# Taken from the same cached pull for the second parser review (no new request either).
SOURCE_FIXTURE_TITLES = [
    "Griffin-Hide Armguards",
    "Wind Rune Meda",
    "Large Empty Crate",
    "Velium Spear",
    "Crushed Diamonds",
    "Morning Dew",
    "Chilled Tundra Root",
    "Fishing Grubs",
    "Chipped Jade",
    "Crude Coal",
    "Keg Mallet",
    "Essence of Earth",
    "Fine Steel Naginata",
    "Shroud of the Sky",
    "Spiroc Beak Earcuff",
]


def fixture_records():
    for title in FIXTURE_TITLES + CRAFTING_FIXTURE_TITLES + PARSER_FIXTURE_TITLES + SOURCE_FIXTURE_TITLES:
        path = FIXTURES / f"{eqlwiki.fixture_slug(title)}.json"
        records = page_records(json.loads(path.read_text(encoding="utf-8")))
        assert len(records) == 1, title
        yield title, records[0]


def test_there_is_one_fixture_file_per_title_and_nothing_else():
    names = sorted(path.name for path in FIXTURES.iterdir())
    titles = FIXTURE_TITLES + CRAFTING_FIXTURE_TITLES + PARSER_FIXTURE_TITLES + SOURCE_FIXTURE_TITLES
    expected = sorted([f"{eqlwiki.fixture_slug(t)}.json" for t in titles] + ["README.md"])
    assert names == expected


def test_every_fixture_is_the_page_it_is_named_for():
    for title, record in fixture_records():
        assert record["title"] == title
        if title == "Dwarven Chain Tunic":
            assert record["missing"] is True  # the wiki has no such page: a test case of its own
        else:
            assert record["ns"] == 0 and record["content"].strip() and "missing" not in record


def test_the_readme_credits_the_wiki_and_lists_every_title_and_revision_id():
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    assert "CC BY-SA 4.0" in readme and "https://eqlwiki.com/" in readme and "eqlwiki contributors" in readme
    for title, record in fixture_records():
        assert title in readme
        if not record.get("missing"):
            assert str(record["revid"]) in readme and str(record["pageid"]) in readme
