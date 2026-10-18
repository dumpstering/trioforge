"""Tests for the release folder and its asset: the tag, the files that ship, ``release.json``, the pointer and the tar.gz.

A release is a folder of results (the folder of every trio, ``items.json`` and ``release.json``) packed into one ``tar.gz``. Nothing here solves
anything: the files are those of the hand-written site fixture (``fixtures/site/results``), with invented names and numbers, and the other
inputs are made up. What the tests hold the code to:

* the tag looks like ``data-YYYY-MM-DD`` with an optional ``-N``, exactly (no trailing newline, no digit of another script);
* only the files of a release are staged: never a chunk, a fingerprint, a seen-flags file or a stray file;
* ``release.json`` carries the evidence map and ``releases/<tag>.json`` never does;
* the pointer is read back as it was written, and refuses a file that has more or less than it should;
* the asset is the same bytes for the same folder, holds nothing it should not, and is read back safely.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
from release_helpers import change_sources

from trioforge.classes import CLASS_CODES
from trioforge.precompute import assemble, grid
from trioforge.precompute.assemble import ReleaseRefused

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "fixtures" / "site" / "results"
SLUG = "pal-mnk-ber"
SHA = "ab" * 32
TAG = "data-2026-10-17"
FILES = sorted(
    [
        "items.json",
        *(f"{SLUG}/{name}" for name in ("defaults.json", "robust.json", "engine-l50.json", "strict-own.json", "strict-group.json", "wiki-own.json", "wiki-group.json")),
        *(f"{SLUG}/runnerups/{name}" for name in ("balanced.json", "melee.json", "tank.json", "index.json")),
    ]
)


def results_copy(tmp_path: Path) -> Path:
    """A scratch copy of the fixture's results (the staging links files, and the committed ones are not for it to link)."""
    target = tmp_path / "results"
    shutil.copytree(RESULTS, target)
    return target


def names_under(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def document(**over):
    """A release document made of invented values (the evidence map is that of three invented items)."""
    values = dict(
        tag=TAG, catalog_date="2026-10-14", catalog_sha256=SHA, rules_version="2026-10-13", rules={"level.current": {"value": 50, "status": "active"}},
        code_hash="cd" * 32, solver={"canonical": True, "highs": "1.15.1"}, build_options={"any_rule": "all", "haste_assumed": None}, level=50,
        game_patch="2026-09-22", trios={SLUG: [0, 4, 10]}, evidence={"w80113": "strict", "w80158": "wiki", "w80392": "hidden"}, snapshot_id="ef" * 16,
        parity_sample="7/36",
    )
    values.update(over)
    return assemble.release_document(**values)


@pytest.fixture
def staged(tmp_path):
    results = results_copy(tmp_path)
    folder = tmp_path / "stage"
    assemble.stage(results, [SLUG], folder)
    return folder


# ---- the tag ---------------------------------------------------------------------------------------------------------------------


def test_the_documented_pattern_of_a_tag_is_exact():
    assert assemble.TAG_PATTERN == r"^data-\d{4}-\d{2}-\d{2}(-\d+)?$"


@pytest.mark.parametrize("tag", ["data-2026-10-17", "data-2026-10-17-2", "data-2026-10-17-12", "data-2030-01-01-0", "data-2026-02-28"])
def test_a_tag_of_the_pattern_is_accepted(tag):
    assert assemble.check_tag(tag) == tag


@pytest.mark.parametrize(
    "tag",
    [
        "",
        "data-2026-10-17-",
        "data-2026-10-1",
        "data-26-10-17",
        "Data-2026-10-17",
        "data-2026-10-17\n",
        "data-2026-10-17-2\n",
        " data-2026-10-17",
        "data-2026-10-17 ",
        "data-2026-10-17-2-3",
        "data-2026-10-17-x",
        "data-2026-10-17/../x",
        "data-2026-10-17;rm",
        "data-\u0662\u0660\u0662\u0666-10-17",  # Arabic-Indic digits: \d matches them in a text pattern, a tag does not
        "data-2026-10-17-\u0663",
        "data-2026-13-17",  # the shape is right but there is no 13th month
        "data-2026-02-30",
        "data-2026-00-10",
    ],
)
def test_anything_else_is_refused_as_a_tag(tag):
    with pytest.raises(ReleaseRefused, match="tag"):
        assemble.check_tag(tag)


def test_a_tag_is_text():
    for bad in (None, 20261017, b"data-2026-10-17"):
        with pytest.raises(ReleaseRefused, match="tag"):
            assemble.check_tag(bad)


# ---- the grid --------------------------------------------------------------------------------------------------------------------


def test_the_grid_is_the_560_trios_of_three_classes_in_class_order():
    trios = assemble.grid_trios()
    assert len(trios) == len(set(trios)) == 560 == 16 * 15 * 14 // 6
    assert SLUG in trios and trios == tuple(sorted(trios, key=lambda slug: [CLASS_CODES.index(code.upper()) for code in slug.split("-")]))
    for slug in trios:
        assert grid.trio_slug(grid.parse_trio(slug)) == slug  # in the form a results folder is named


# ---- staging the files -----------------------------------------------------------------------------------------------------------


def test_the_files_of_a_release_are_the_item_table_and_the_files_of_each_trio_and_nothing_else(tmp_path):
    results = results_copy(tmp_path)
    chunks = results / SLUG / "chunks"
    chunks.mkdir()
    (chunks / "s-wiki-own-balanced-dw-t04.json").write_text('{"fingerprint": "00", "rows": []}', encoding="utf-8")
    report = assemble.stage(results, [SLUG], tmp_path / "stage")
    assert names_under(tmp_path / "stage") == FILES
    assert report.trios == (SLUG,) and report.missing == () and report.files == len(FILES) and report.bytes > 0
    assert report.linked + report.copied == report.files


def test_a_staged_file_is_the_file_of_the_results_byte_for_byte(tmp_path):
    results = results_copy(tmp_path)
    assemble.stage(results, [SLUG], tmp_path / "stage")
    for name in FILES:
        assert (tmp_path / "stage" / name).read_bytes() == (results / name).read_bytes(), name


def test_a_trio_with_no_folder_is_reported_missing_and_not_staged(tmp_path):
    results = results_copy(tmp_path)
    report = assemble.stage(results, ["clr-shd-ber", SLUG, "war-clr-pal"], tmp_path / "stage")
    assert report.trios == (SLUG,) and report.missing == ("clr-shd-ber", "war-clr-pal")
    assert names_under(tmp_path / "stage") == FILES


def test_a_trio_outside_the_results_folder_is_not_staged_unless_asked_for(tmp_path):
    results = results_copy(tmp_path)
    shutil.copytree(results / SLUG, results / "clr-shd-ber")
    assemble.stage(results, [SLUG], tmp_path / "stage")
    assert names_under(tmp_path / "stage") == FILES


@pytest.mark.parametrize(
    "stray",
    ["seen-flags.json", "notes.txt", "engine-l50.json.bak", "catalog.json", "fingerprint.json", "runnerups/extra/x.json", "runnerups/healer.json", "sub/x.json", "engine-lx.json"],
)
def test_a_file_that_is_not_part_of_a_release_is_refused_where_it_is_found(tmp_path, stray):
    results = results_copy(tmp_path)
    path = results / SLUG / stray
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ReleaseRefused, match=re.escape(f"{SLUG}/{stray}")):
        assemble.stage(results, [SLUG], tmp_path / "stage")
    assert not (tmp_path / "stage").exists() or names_under(tmp_path / "stage") == []  # nothing is left half staged


def test_the_item_table_is_needed(tmp_path):
    results = results_copy(tmp_path)
    (results / "items.json").unlink()
    with pytest.raises(ReleaseRefused, match=r"items\.json"):
        assemble.stage(results, [SLUG], tmp_path / "stage")


def test_a_staging_folder_with_something_in_it_is_refused(tmp_path):
    results = results_copy(tmp_path)
    (tmp_path / "stage").mkdir()
    (tmp_path / "stage" / "old.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="not empty"):
        assemble.stage(results, [SLUG], tmp_path / "stage")


def test_staging_copies_when_the_files_cannot_be_linked(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("no links on this volume")

    monkeypatch.setattr(os, "link", refuse)
    results = results_copy(tmp_path)
    report = assemble.stage(results, [SLUG], tmp_path / "stage")
    assert report.copied == len(FILES) and report.linked == 0
    assert names_under(tmp_path / "stage") == FILES
    assert not os.path.samefile(results / "items.json", tmp_path / "stage" / "items.json")  # a copy: changing the results later cannot change the release


def test_a_copy_that_differs_from_its_source_is_refused(tmp_path, monkeypatch):
    results = results_copy(tmp_path)  # (made before the copy is spoiled)

    def no_links(*args, **kwargs):
        raise OSError("no links on this volume")

    def garble(source, target, *args, **kwargs):
        data = bytearray(Path(source).read_bytes())
        data[-1] ^= 1
        Path(target).write_bytes(bytes(data))
        return target

    monkeypatch.setattr(os, "link", no_links)
    monkeypatch.setattr(shutil, "copyfile", garble)
    with pytest.raises(ReleaseRefused, match="differs from"):
        assemble.stage(results, [SLUG], tmp_path / "stage")
    assert not (tmp_path / "stage").exists() or names_under(tmp_path / "stage") == []


def test_a_link_in_the_results_is_refused(tmp_path):
    results = results_copy(tmp_path)
    try:
        os.symlink(results / SLUG / "defaults.json", results / SLUG / "runnerups" / "balanced-link.json")
    except (OSError, NotImplementedError):
        pytest.skip("this machine cannot create symbolic links")
    with pytest.raises(ReleaseRefused, match="link"):
        assemble.stage(results, [SLUG], tmp_path / "stage")


def make_junction(link: Path, target: Path) -> None:
    """A directory link that needs no privilege on Windows (a junction), or a symbolic link elsewhere; the test is skipped where neither can be made."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        made = os.name == "nt" and subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True).returncode == 0
        if not made:
            pytest.skip("this machine cannot create a directory link")


def test_a_folder_link_in_the_results_is_refused_inside_a_trio_and_as_a_trio(tmp_path):
    results = results_copy(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "x.json").write_text("{}", encoding="utf-8")
    make_junction(results / SLUG / "runnerups-link", elsewhere)
    with pytest.raises(ReleaseRefused, match="link"):
        assemble.stage(results, [SLUG], tmp_path / "stage1")
    os.rmdir(results / SLUG / "runnerups-link")  # (removes the link, never what it points at)
    make_junction(results / "war-clr-pal", elsewhere)
    with pytest.raises(ReleaseRefused, match="link"):
        assemble.stage(results, [SLUG, "war-clr-pal"], tmp_path / "stage2")
    assert (elsewhere / "x.json").is_file()


# ---- what a release must not hold --------------------------------------------------------------------------------------------------


def test_a_clean_release_passes_the_content_check(staged):
    assert assemble.check_clean(staged) == len(FILES)


def test_a_file_that_names_the_seen_reason_is_refused(staged):
    shard = staged / SLUG / "wiki-own.json"
    shard.unlink()  # a staged file may be a link to the results: replace it, never write through it
    shard.write_text('{"reasons": [{"code": "seen-in-game"}]}', encoding="utf-8")
    with pytest.raises(ReleaseRefused, match=r"wiki-own\.json.*seen"):
        assemble.check_clean(staged)


@pytest.mark.parametrize("text", ['{"fingerprint": "ab"}', '{"a": {"b": [{"fingerprint":"ab"}]}}', '{\n "Fingerprint" : 1}'])
def test_a_fingerprint_field_is_refused_wherever_it_is(staged, text):
    target = staged / SLUG / "defaults.json"
    target.unlink()
    target.write_text(text, encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="fingerprint"):
        assemble.check_clean(staged)


def test_the_word_fingerprint_inside_a_text_is_no_field(staged):
    target = staged / SLUG / "defaults.json"
    target.unlink()
    target.write_text('{"note": "a fingerprint scanner"}', encoding="utf-8")
    assert assemble.check_clean(staged) == len(FILES)


def test_the_published_inputs_field_is_not_a_fingerprint_of_the_flags(staged, tmp_path):
    """The bundle and the item table carry ``inputs``, the digest of the catalog and the levels: it is what the site build compares, and it is allowed. It is made of
    the levels and not of the flags: two sets of flags with the same effective levels give the very same bundle and item table, whatever else is in them."""
    assert '"inputs"' in (staged / "items.json").read_text(encoding="utf-8")
    assert assemble.check_clean(staged) == len(FILES)
    from test_precompute import CATALOG, write_catalog, write_seen

    from trioforge.model import tables as tables_module
    from trioforge.precompute import engine

    catalog = write_catalog(tmp_path / "catalog.json", CATALOG)
    codes = grid.parse_trio("pal-mnk-ber")

    def export(name, keys):
        seen = write_seen(tmp_path / f"{name}.json", keys)
        config, meta = grid.load_inputs(codes, catalog_path=catalog, seen_path=seen)
        texts = engine.make(codes, config, meta, tables_module.load(config.tables_root), catalog_path=catalog, seen_path=seen, setups={})
        return json.loads(texts.bundle), json.loads(texts.items), texts

    base = {"w9001", "w9002"}
    bundle_a, items_a, texts_a = export("a", base)
    bundle_b, items_b, texts_b = export("b", base | {"w99998", "w99999"})  # flags for items the catalog does not know: the same levels
    assert re.fullmatch(r"[0-9a-f]{64}", bundle_a["inputs"])
    assert bundle_a["inputs"] == bundle_b["inputs"] == items_a["inputs"] == items_b["inputs"]
    assert texts_a.bundle == texts_b.bundle and texts_a.items == texts_b.items
    bundle_c, items_c, _ = export("c", base | {"w9004"})  # one more item is strict: the levels are not the same, and the field says so
    assert bundle_c["inputs"] == items_c["inputs"] != bundle_a["inputs"]
    assert not any(key in json.dumps([bundle_a, items_a]) for key in ("w99998", "w99999"))


def test_the_manifest_lists_every_file_with_its_size_and_digest(staged):
    listed = assemble.manifest(staged)
    assert sorted(listed) == FILES
    for name, (size, digest) in listed.items():
        data = (staged / name).read_bytes()
        assert size == len(data) and digest == hashlib.sha256(data).hexdigest()


# ---- the evidence map ----------------------------------------------------------------------------------------------------------------


def test_the_evidence_map_is_the_level_of_every_record_of_the_item_table():
    table = json.loads((RESULTS / "items.json").read_text(encoding="utf-8"))
    found = assemble.evidence_map(table)
    assert len(found) == table["count"] == 48
    assert found["w8091"] == "strict" and set(found.values()) <= {"strict", "wiki", "disputed", "hidden"}
    assert list(found) == sorted(found)  # in key order, so that the same table is the same text


def test_a_record_with_no_key_is_known_by_its_page(tmp_path):
    table = {"items": [{"id": 77, "name": "Invented Cap", "evidence": {"level": "wiki"}}, {"id": 78, "key": "rinvented-ring", "name": "x", "evidence": {"level": "hidden"}}]}
    assert assemble.evidence_map(table) == {"rinvented-ring": "hidden", "w77": "wiki"}


@pytest.mark.parametrize(
    "table",
    [{}, {"items": "x"}, {"items": [{"id": 1, "name": "x"}]}, {"items": [{"id": 1, "evidence": {"level": "gold"}}]}, {"items": [{"id": 1, "evidence": {"level": "wiki"}}, {"id": 1, "evidence": {"level": "wiki"}}]}],
)
def test_a_table_that_cannot_give_an_evidence_map_is_refused(table):
    with pytest.raises(ReleaseRefused, match="item table"):
        assemble.evidence_map(table)


# ---- release.json ----------------------------------------------------------------------------------------------------------------


def test_release_json_has_what_a_release_is_made_of_and_the_evidence_map():
    doc = document()
    assert list(doc) == list(assemble.RELEASE_KEYS)
    assert doc["release"] == TAG and doc["catalog_date"] == "2026-10-14" and doc["trios"] == {SLUG: [0, 4, 10]}
    assert doc["evidence"] == {"w80113": "strict", "w80158": "wiki", "w80392": "hidden"} and doc["trial"] is False
    assert doc["parity_sample"] == "7/36"  # the sample of the parity suite that this release was held to
    assert doc["format"] == assemble.FORMAT == 1
    assert re.fullmatch(r"[0-9a-f]{32}", doc["snapshot_id"])


def test_a_release_json_is_written_and_read_back_as_it_was(tmp_path):
    doc = document()
    (tmp_path / "r").mkdir()
    assemble.write_release_json(tmp_path / "r", doc)
    assert (tmp_path / "r" / "release.json").read_text(encoding="utf-8").endswith("\n")
    assert assemble.read_release_json(tmp_path / "r") == doc
    before = (tmp_path / "r" / "release.json").read_bytes()
    assemble.write_release_json(tmp_path / "r", doc)
    assert (tmp_path / "r" / "release.json").read_bytes() == before  # the same document is the same bytes


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"tag": "data-2026-1-17"}, "tag"),
        ({"catalog_sha256": "xyz"}, "catalog_sha256"),
        ({"code_hash": SHA.upper()}, "code_hash"),
        ({"snapshot_id": "abc"}, "snapshot_id"),
        ({"catalog_date": "2026-13-01"}, "catalog_date"),
        ({"rules_version": "13"}, "rules_version"),
        ({"trios": {}}, "trios"),
        ({"trios": {"pal-mnk-ber": []}}, "tiers"),
        ({"trios": {"pal-mnk-ber": [4, 0]}}, "tiers"),
        ({"trios": {"pal-mnk-ber": [0, 11]}}, "tiers"),
        ({"trios": {"PAL-MNK-BER": [0, 4]}}, "trios"),
        ({"evidence": {"w1": "gold"}}, "evidence"),
        ({"evidence": {"Not A Key": "wiki"}}, "evidence"),
        ({"level": 0}, "level"),
        ({"trial": "no"}, "trial"),
        ({"parity_sample": "5"}, "parity_sample"),
        ({"parity_sample": "a/b"}, "parity_sample"),
        ({"parity_sample": "36/36"}, "parity_sample"),
        ({"parity_sample": "0/0"}, "parity_sample"),
        ({"parity_sample": "-1/4"}, "parity_sample"),
        ({"parity_sample": None}, "parity_sample"),
        ({"parity_sample": 7}, "parity_sample"),
    ],
)
def test_a_release_document_that_is_not_one_is_refused(change, message):
    with pytest.raises(ReleaseRefused, match=message):
        document(**change)


def test_a_release_json_with_another_field_or_a_missing_one_is_refused_on_reading(tmp_path):
    (tmp_path / "r").mkdir()
    doc = document()
    for broken in ({**doc, "extra": 1}, {k: v for k, v in doc.items() if k != "evidence"}, {**doc, "format": 2}):
        (tmp_path / "r" / "release.json").write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(ReleaseRefused, match=r"release\.json"):
            assemble.read_release_json(tmp_path / "r")
    (tmp_path / "r" / "release.json").unlink()
    with pytest.raises(ReleaseRefused, match=r"release\.json"):
        assemble.read_release_json(tmp_path / "r")


def test_every_snapshot_id_is_new_and_random():
    ids = {assemble.new_snapshot_id() for _ in range(50)}
    assert len(ids) == 50 and all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)


# ---- releases/<tag>.json ----------------------------------------------------------------------------------------------------------------


def test_the_pointer_holds_only_what_the_deploy_checks_and_never_the_evidence_map():
    pointer = assemble.pointer_document(document(), "12" * 32)
    assert list(pointer) == list(assemble.POINTER_KEYS)
    assert set(assemble.POINTER_KEYS) == {
        "format", "release", "asset_sha256", "catalog_sha256", "catalog_date", "rules_version", "code_hash", "solver", "build_options", "snapshot_id",
    }  # fmt: skip
    for left_out in ("evidence", "trios", "rules", "level", "game_patch", "trial"):
        assert left_out not in pointer
    text = json.dumps(pointer)
    for key in ("w80113", "w80158", "w80392", SLUG, "strict"):
        assert key not in text, key  # no item, no trio and no evidence level reaches git
    assert pointer["asset_sha256"] == "12" * 32 and pointer["catalog_sha256"] == SHA and pointer["snapshot_id"] == "ef" * 16


def test_the_pointer_is_written_and_read_back_as_it_was(tmp_path):
    pointer = assemble.pointer_document(document(), "12" * 32)
    path = tmp_path / "releases" / f"{TAG}.json"
    assemble.write_pointer(path, pointer)
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert assemble.read_pointer(path) == pointer
    assert assemble.read_pointer(path) == json.loads(path.read_text(encoding="utf-8"))


def test_the_pointer_of_a_tag_with_a_serial_is_named_for_it(tmp_path):
    pointer = assemble.pointer_document(document(tag="data-2026-10-17-3"), "12" * 32)
    path = tmp_path / "releases" / "data-2026-10-17-3.json"
    assemble.write_pointer(path, pointer)
    assert assemble.read_pointer(path)["release"] == "data-2026-10-17-3"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(evidence={"w1": "strict"}),
        lambda p: p.pop("snapshot_id"),
        lambda p: p.update(asset_sha256="12" * 31),
        lambda p: p.update(asset_sha256="XY" * 32),
        lambda p: p.update(code_hash="12" * 32 + "0"),
        lambda p: p.update(release="data-2026-10-18"),  # not the tag in the file's name
        lambda p: p.update(release="nope"),
        lambda p: p.update(format=2),
        lambda p: p.update(catalog_date="2026-02-31"),
        lambda p: p.update(solver=[]),
        lambda p: p.update(snapshot_id="12" * 17),
    ],
)
def test_a_pointer_that_is_not_one_is_refused_on_reading(tmp_path, mutate):
    pointer = assemble.pointer_document(document(), "12" * 32)
    mutate(pointer)
    path = tmp_path / f"{TAG}.json"
    path.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="pointer"):
        assemble.read_pointer(path)


def test_the_pointer_is_made_from_the_release_so_that_the_two_cannot_disagree():
    doc = document()
    pointer = assemble.pointer_document(doc, "12" * 32)
    for name in ("release", "catalog_sha256", "catalog_date", "rules_version", "code_hash", "solver", "build_options", "snapshot_id", "format"):
        assert pointer[name] == doc[name], name


# ---- the asset ----------------------------------------------------------------------------------------------------------------------------


def packed(tmp_path, staged_folder, name="a.tar.gz"):
    path = tmp_path / name
    return path, assemble.pack(staged_folder, path)


def test_packing_gives_the_same_bytes_for_the_same_folder(tmp_path, staged):
    first, digest = packed(tmp_path, staged, "a.tar.gz")
    second, other = packed(tmp_path, staged, "b.tar.gz")
    assert first.read_bytes() == second.read_bytes() and digest == other == hashlib.sha256(first.read_bytes()).hexdigest()


def test_the_asset_holds_the_files_of_the_folder_flat_sorted_and_with_no_dates_or_owners(tmp_path, staged):
    path, _ = packed(tmp_path, staged)
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
    assert [m.name for m in members] == FILES == sorted(m.name for m in members)
    for member in members:
        assert member.isreg() and member.mtime == 0 and member.uid == member.gid == 0 and member.uname == member.gname == ""
        assert member.mode == 0o644 and not member.name.startswith(("/", "./")) and ".." not in member.name.split("/")
    assert path.read_bytes()[4:8] == bytes(4)  # the gzip header's own time is 0 too
    assert gzip.decompress(path.read_bytes())  # (and it is a gzip stream)


def test_the_asset_extracts_into_a_folder_of_results(tmp_path, staged):
    path, _ = packed(tmp_path, staged)
    assemble.extract(path, tmp_path / "out")
    assert names_under(tmp_path / "out") == FILES
    for name in FILES:
        assert (tmp_path / "out" / name).read_bytes() == (staged / name).read_bytes()


def test_the_asset_holds_no_chunk_no_fingerprint_and_no_seen_file(tmp_path):
    results = results_copy(tmp_path)
    chunks = results / SLUG / "chunks"
    chunks.mkdir()
    (chunks / "s-wiki-own-balanced-dw-t04.json").write_text('{"fingerprint": "00", "rows": []}', encoding="utf-8")
    (results / "seen-flags.json").write_text('{"version": 1, "license": "x", "keys": ["w1"]}', encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "catalog.json").write_text('{"reasons": [{"code": "seen-in-game"}]}', encoding="utf-8")
    staging = tmp_path / "stage"
    assemble.stage(results, [SLUG], staging)
    assemble.write_release_json(staging, document())
    assemble.check_clean(staging)
    path, _ = packed(tmp_path, staging)
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        assert "release.json" in names
        for member in archive.getmembers():
            text = archive.extractfile(member).read().decode("utf-8")
            assert "chunks" not in member.name and "seen" not in member.name and "catalog" not in member.name, member.name
            assert "fingerprint" not in text.lower() and "seen-in-game" not in text, member.name


def test_the_evidence_map_is_in_the_asset_and_never_in_the_pointer(tmp_path, staged):
    assemble.write_release_json(staged, document())
    path, digest = packed(tmp_path, staged)
    with tarfile.open(path, "r:gz") as archive:
        inside = json.loads(archive.extractfile("release.json").read())
    assert inside["evidence"] == {"w80113": "strict", "w80158": "wiki", "w80392": "hidden"}
    pointer_path = tmp_path / "releases" / f"{TAG}.json"
    assemble.write_pointer(pointer_path, assemble.pointer_document(inside, digest))
    assert "evidence" not in pointer_path.read_text(encoding="utf-8") and "w80113" not in pointer_path.read_text(encoding="utf-8")


def test_the_asset_is_checked_against_the_manifest_of_what_was_scanned(tmp_path, staged):
    wanted = assemble.manifest(staged)
    path, _ = packed(tmp_path, staged)
    assemble.verify_asset(path, wanted)  # the same files
    changed = dict(wanted)
    name = sorted(changed)[0]
    changed[name] = (changed[name][0], "00" * 32)
    with pytest.raises(ReleaseRefused, match=re.escape(name)):
        assemble.verify_asset(path, changed)
    extra = dict(wanted)
    extra["added.json"] = (2, "11" * 32)
    with pytest.raises(ReleaseRefused, match=r"added\.json"):
        assemble.verify_asset(path, extra)
    short = {k: v for k, v in wanted.items() if k != name}
    with pytest.raises(ReleaseRefused, match=re.escape(name)):
        assemble.verify_asset(path, short)


def archive_with(path: Path, members: list[tuple[str, bytes, bytes | None]]) -> Path:
    """A tar.gz of ``(name, data, type)`` members, made by hand so that a hostile one can be built."""
    with tarfile.open(path, "w:gz") as archive:
        for name, data, kind in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            if kind == b"symlink":
                info.type, info.linkname, info.size = tarfile.SYMTYPE, "target", 0
                archive.addfile(info)
            else:
                archive.addfile(info, io.BytesIO(data))
    return path


@pytest.mark.parametrize(
    "name",
    ["../escape.json", "a/../../escape.json", "/abs.json", "C:/abs.json", "a\\b.json", "./x.json", "a//b.json", "a/./b.json", "CON/x", "a/b ", "a/b."],
)
def test_extracting_refuses_a_name_that_could_leave_the_folder(tmp_path, name):
    path = archive_with(tmp_path / "bad.tar.gz", [(name, b"{}", None)])
    with pytest.raises(ReleaseRefused, match="member"):
        assemble.extract(path, tmp_path / "out")
    assert not (tmp_path / "escape.json").exists()


def test_extracting_refuses_a_link_a_repeated_name_and_a_file_too_large(tmp_path):
    with pytest.raises(ReleaseRefused, match="member"):
        assemble.extract(archive_with(tmp_path / "l.tar.gz", [("a.json", b"", b"symlink")]), tmp_path / "o1")
    with pytest.raises(ReleaseRefused, match="twice"):
        assemble.extract(archive_with(tmp_path / "d.tar.gz", [("a.json", b"1", None), ("a.json", b"2", None)]), tmp_path / "o2")
    with pytest.raises(ReleaseRefused, match="larger"):
        assemble.extract(archive_with(tmp_path / "s.tar.gz", [("a.json", b"x" * 100, None)]), tmp_path / "o3", max_member=10)


def test_extracting_into_a_folder_that_has_files_is_refused(tmp_path, staged):
    path, _ = packed(tmp_path, staged)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "x").write_text("x", encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="not empty"):
        assemble.extract(path, tmp_path / "out")


# ---- the code that writes the files of a trio --------------------------------------------------------------------------------------------------
#
# The code hash of a chunk covers what decides a solve. The files of a trio are also shaped by the code that writes them (the shards, the defaults, the seals,
# the bundle, the item table); the code hash of a release covers that as well, so that the deploy check sees a release whose writers changed, and a trio that
# was finished before such a change is written again.

#: the modules the writers import that no hash covers, each with why no published file depends on its code
WRITER_NOT_HASHED = {
    "trioforge.data.catalog": "reads the seen-flags file (the keys pass through unchanged) and refuses a folder a build may not write to; the catalog it builds is hashed as a file",
    "trioforge.sources.client_tables": "writes files whole or not at all: the bytes it is given are the bytes written",
}


def test_the_files_that_write_a_trio_are_named_and_all_of_them_exist():
    assert assemble.WRITER_FILES == tuple(sorted(assemble.WRITER_FILES))
    root = Path(assemble.__file__).resolve().parents[1]
    assert all((root / name).is_file() for name in assemble.WRITER_FILES)
    assert {"precompute/__init__.py", "precompute/shards.py", "precompute/seals.py", "precompute/engine.py", "export/browser.py"} <= set(assemble.WRITER_FILES)


def test_the_code_hash_of_a_release_covers_the_code_of_the_chunks_and_the_code_that_writes_the_files():
    combined = hashlib.sha256(f"chunks {grid._code_hash()}\nwriters {assemble.writer_hash()}".encode()).hexdigest()
    assert assemble.code_hash() == combined and re.fullmatch(r"[0-9a-f]{64}", assemble.code_hash())
    assert assemble.code_hash() not in (grid._code_hash(), assemble.writer_hash())


@pytest.mark.parametrize("name", ["precompute/__init__.py", "precompute/shards.py", "precompute/seals.py", "precompute/engine.py", "export/browser.py", "data/jsonio.py", "scope.py"])
def test_a_change_in_a_file_that_writes_a_trio_changes_the_code_hash_of_the_release_and_not_that_of_the_chunks(monkeypatch, name):
    before = (assemble.code_hash(), assemble.writer_hash(), grid._code_hash())
    change_sources(monkeypatch, name)
    after = (assemble.code_hash(), assemble.writer_hash(), grid._code_hash())
    assert after[0] != before[0] and after[1] != before[1]
    assert after[2] == before[2]  # (the chunks are made under the same code: none of them is made again)


def test_a_change_in_the_code_of_the_chunks_changes_the_code_hash_of_the_release_too(monkeypatch):
    before = (assemble.code_hash(), assemble.writer_hash())
    change_sources(monkeypatch, "sources/client_spells.py")
    assert assemble.code_hash() != before[0] and assemble.writer_hash() == before[1]


def test_line_endings_do_not_change_the_code_hash(monkeypatch):
    before = assemble.code_hash()
    root = Path(assemble.__file__).resolve().parents[1]
    target = (root / "precompute" / "shards.py").resolve()
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: real(path).replace(b"\n", b"\r\n") if Path(path).resolve() == target else real(path))
    assert assemble.code_hash() == before


def test_every_module_the_writers_import_is_hashed_or_says_why_it_need_not_be():
    from test_precompute_checks import imports_of, is_marker, module_file, module_name

    root = Path(assemble.__file__).resolve().parents[1]
    writers = {module_name(root / name) for name in assemble.WRITER_FILES}
    chunked = {module_name(path) for path in grid.code_files()}
    unexplained: dict[str, list[str]] = {}
    reached: set[str] = set()
    for name in sorted(writers):
        for imported in imports_of(module_file(name)):
            if imported in writers or imported in chunked:
                continue
            reached.add(imported)
            if imported not in WRITER_NOT_HASHED and not is_marker(module_file(imported)):
                unexplained.setdefault(imported, []).append(name)
    assert not unexplained, f"imported by a module that writes a trio, and neither hashed (assemble.WRITER_FILES) nor explained in WRITER_NOT_HASHED: {unexplained}"
    assert set(WRITER_NOT_HASHED) <= reached, f"no longer imported, take them out: {sorted(set(WRITER_NOT_HASHED) - reached)}"
    assert not set(WRITER_NOT_HASHED) & (writers | chunked)
