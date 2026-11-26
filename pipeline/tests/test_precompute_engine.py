"""The engine's data files of a precompute run: ``<trio>/engine-l<level>.json`` and ``<results>/items.json``.

The browser's engine needs two things the shards do not hold: the bundle of the trio (profiles, buff sets, constants, tier and
weapon rules) and the table of every wearable item. A run writes both beside its shards, from the inputs it solved with, so that
their evidence levels are the ones the shards were made with: the catalog document the run was given and the maintainer's private
seen flags (merged into the item table and into the pools that decide the weapon setups of each level). The bundle belongs to
one trio and level; the item table is one file for the whole results folder, which every run of every trio writes, and a run that
finds an identical one leaves it alone.

Every name, item and number here is invented (the tiny catalog of ``test_precompute.py``).
"""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_precompute import CATALOG, RULES, SLUG, SPELLS, TABLES, TRIO, read, write_catalog, write_seen

from trioforge import precompute as pc
from trioforge.export import browser
from trioforge.precompute import engine as engine_module
from trioforge.precompute import grid, shards

NARROW = dict(races=("OGR",), roles=("tank",), tiers=(4,), robustness=False)  # one race, one role, one tier: a few seconds
# the same keys as test_site_integration: a strict level that wears things, with a shield in it (w9014)
SEEN = {"w9001", "w9002", "w9003", "w9006", "w9007", "w9009", "w9011", "w9012", "w9014", "w9015", "w9021"}
WITH_SHIELD, WITHOUT_SHIELD = ["1h-shield", "2h", "dw"], ["2h", "dw"]


def catalog_document(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """One narrowed run of the invented catalog with seen flags: its folder of results, catalog and seen file."""
    root = tmp_path_factory.mktemp("engine-files")
    catalog = write_catalog(root / "catalog.json")
    seen = write_seen(root / "seen.json", SEEN)
    out = root / "out"
    summary = pc.run(SLUG, out, seen_path=seen, catalog=catalog, processes=1, **NARROW)
    return SimpleNamespace(root=root, catalog=catalog, seen=seen, out=out, dir=out / SLUG, summary=summary)


@pytest.fixture(scope="module")
def plain(tmp_path_factory):
    """The same run without seen flags."""
    root = tmp_path_factory.mktemp("engine-files-plain")
    catalog = write_catalog(root / "catalog.json")
    out = root / "out"
    summary = pc.run(SLUG, out, catalog=catalog, processes=1, **NARROW)
    return SimpleNamespace(root=root, catalog=catalog, out=out, dir=out / SLUG, summary=summary)


@pytest.fixture
def again(run, tmp_path):
    """A copy of the results folder of the run, to run in again (the finished chunks are kept, so a rerun is quick)."""
    out = tmp_path / "out"
    shutil.copytree(run.out, out)
    return SimpleNamespace(out=out, dir=out / SLUG, catalog=run.catalog, seen=run.seen)


def rerun(where, **options):
    return pc.run(SLUG, where.out, seen_path=where.seen, catalog=where.catalog, processes=1, **{**NARROW, **options})


# ---- where the files are and what the run says about them ---------------------------------------------------------------------


def test_a_run_writes_the_bundle_beside_the_shards_and_one_item_table_beside_the_trio_folders(run):
    assert (run.dir / "engine-l50.json").is_file() and (run.out / "items.json").is_file()
    assert shards.engine_name(50) == "engine-l50.json" and shards.ITEMS_NAME == "items.json"
    written = {path.relative_to(run.out).as_posix() for path in run.summary.files}
    assert {f"{SLUG}/engine-l50.json", "items.json"} <= written
    for name, path in (("engine-l50.json", run.dir / "engine-l50.json"), ("../items.json", run.out / "items.json")):
        data = path.read_bytes()
        assert run.summary.sizes[name] == (len(data), shards.gzip_size(data)), name
    assert not list(run.out.rglob("*.tmp")) and not [p for p in run.out.iterdir() if p.name.startswith(".")]
    assert not run.summary.violations and run.summary.partial is True  # a narrowed run writes them too


def inputs_of(where):
    """The fingerprint of the inputs of a run, worked out here from the catalog file and the item table, as the module docstring says."""
    return browser.inputs_fingerprint(hashlib.sha256(Path(where.catalog).read_bytes()).hexdigest(), browser.items(catalog_document(where.catalog), RULES, seen=SEEN))


def test_the_bundle_is_the_exporters_for_the_catalog_and_the_seen_flags_of_the_run_with_the_fingerprint_of_its_inputs(run):
    document = catalog_document(run.catalog)
    made = browser.bundle(TRIO, 50, TABLES, RULES, SPELLS, data_release="data-2030-01-02", catalog=document, seen=SEEN)
    expected = browser.render_bundle(browser.with_inputs(made, inputs_of(run)))
    assert (run.dir / "engine-l50.json").read_text(encoding="utf-8") == expected


def test_the_item_table_is_the_exporters_for_the_catalog_and_the_seen_flags_of_the_run_with_the_fingerprint_of_its_inputs(run):
    document = catalog_document(run.catalog)
    expected = browser.render_items(browser.with_inputs(browser.items(document, RULES, seen=SEEN), inputs_of(run)))
    assert (run.out / "items.json").read_text(encoding="utf-8") == expected


def test_the_two_files_are_made_from_the_catalog_the_run_was_given_and_never_from_another(run, tmp_path, monkeypatch):
    table = read(run.out / "items.json")
    keys = {record.get("key") or f"w{record['id']}" for record in table["items"]}
    assert keys <= {item["key"] for item in CATALOG} and "w9001" in keys and "w112" not in keys  # not derived/catalog.json
    assert table["data_release"] == "data-2030-01-02" == read(run.dir / "engine-l50.json")["data_release"]

    def refuse(*_):
        raise AssertionError("the run looked for the default catalog")

    monkeypatch.setattr(grid, "find_catalog", refuse)
    monkeypatch.setattr(browser, "_found_catalog", refuse)
    again_in_a_new_folder = pc.run(SLUG, tmp_path / "other", seen_path=run.seen, catalog=run.catalog, processes=1, **NARROW)
    assert again_in_a_new_folder.violations == []
    assert (tmp_path / "other" / "items.json").read_bytes() == (run.out / "items.json").read_bytes()


# ---- the evidence levels are the ones the run solved with ---------------------------------------------------------------------


def levels_of(table):
    return {(record.get("key") or f"w{record['id']}"): record["evidence"]["level"] for record in table["items"]}


def test_the_item_table_carries_the_levels_the_shards_were_made_with(run):
    table = read(run.out / "items.json")
    levels = levels_of(table)
    assert levels["w9001"] == "strict" and levels["w9014"] == "strict"  # wiki items that were seen
    assert levels["w9004"] == "wiki" and levels["w9017"] == "hidden"  # not seen: the catalog's own
    assert [r for r in table["items"] if r.get("owned_only")] and "owned_only" not in next(r for r in table["items"] if r["id"] == 9001)
    for name in shards.SHARD_NAMES:
        for row in read(run.dir / name)["items"]:
            assert levels[row[0]] == row[6], (name, row[0])  # every item a shard shows has the level the table gives it
        for row in read(run.dir / "runnerups" / "tank.json")["items"]:
            assert levels[row[0]] == row[6], ("runner-ups", row[0])


def test_without_seen_flags_the_levels_are_the_catalogs_and_the_files_differ(run, plain):
    assert set(levels_of(read(plain.out / "items.json")).values()) == {"wiki", "disputed", "hidden"}  # the invented catalog has no strict item
    assert (plain.out / "items.json").read_bytes() != (run.out / "items.json").read_bytes()
    strict = read(run.dir / "engine-l50.json")["roles"]["tank"]["setups_by_evidence"]
    bare = read(plain.dir / "engine-l50.json")["roles"]["tank"]["setups_by_evidence"]
    assert strict == {"strict": WITH_SHIELD, "wiki": WITH_SHIELD}  # the seen shield is in the strict pool
    assert bare == {"strict": WITHOUT_SHIELD, "wiki": WITH_SHIELD}  # no strict item: no strict shield


def test_the_bundle_says_what_the_shards_say_about_the_run_and_the_weapon_setups_of_their_rows(run):
    bundle = read(run.dir / "engine-l50.json")
    for name in shards.SHARD_NAMES:
        shard = read(run.dir / name)
        assert (bundle["data_release"], bundle["rules_version"], bundle["level"]) == (shard["data_release"], shard["rules_version"], shard["level"])
        assert bundle["trio"] == shard["classes"] == list(TRIO)
        for role, setups in shard["setups"].items():
            assert bundle["roles"][role]["setups_by_evidence"][shard["evidence"]] == setups, (name, role)


# ---- the fingerprint of the inputs -------------------------------------------------------------------------------------------


def test_both_files_carry_the_fingerprint_of_the_inputs_of_the_run_after_the_rules_version(run):
    table, bundle = read(run.out / "items.json"), read(run.dir / "engine-l50.json")
    assert table["inputs"] == bundle["inputs"] == inputs_of(run) and re.fullmatch(r"[0-9a-f]{64}", table["inputs"])
    assert list(table)[:4] == ["version", "data_release", "rules_version", "inputs"]
    assert list(bundle)[:4] == ["version", "data_release", "rules_version", "inputs"]
    assert any(name == "inputs" for name in browser.ITEM_TABLE_FIELDS) is False  # an optional field: the exporter's own files have none


def test_the_fingerprint_follows_the_inputs_of_the_run(run, plain):
    with_flags, without = read(run.out / "items.json")["inputs"], read(plain.out / "items.json")["inputs"]
    assert with_flags != without  # other flags, other levels
    assert read(plain.dir / "engine-l50.json")["inputs"] == without  # the bundle and the table of one run share it


def test_a_flag_that_changes_no_level_changes_no_byte_of_the_files_and_the_fingerprint_is_not_a_digest_of_the_flags(run, tmp_path):
    flags = write_seen(tmp_path / "seen.json", SEEN | {"w99404"})  # a key that no item of the catalog has: no level changes
    summary = pc.run(SLUG, tmp_path / "out", seen_path=flags, catalog=run.catalog, processes=1, **NARROW)
    assert summary.violations == []
    for name in ("items.json", f"{SLUG}/engine-l50.json"):
        assert (tmp_path / "out" / name).read_bytes() == (run.out / name).read_bytes(), name
    # and no digest of the flags is in the files: the one the chunk files are fingerprinted with is not
    raw_digest = hashlib.sha256("\n".join(sorted(SEEN)).encode()).hexdigest()
    for path in (run.dir / "engine-l50.json", run.out / "items.json"):
        assert raw_digest not in path.read_text(encoding="utf-8"), path.name


def test_neither_file_says_that_a_flag_was_merged_or_where_the_flags_are(run):
    for path in (run.dir / "engine-l50.json", run.out / "items.json"):
        text = path.read_text(encoding="utf-8")
        assert "seen" not in text.lower() and str(run.seen) not in text and "seen-in-game" not in text, path.name


# ---- the item table is one file for the folder -------------------------------------------------------------------------------


def test_a_run_that_finds_an_identical_item_table_leaves_it_alone(again):
    path = again.out / "items.json"
    before, stamp = path.read_bytes(), path.stat().st_mtime_ns
    summary = rerun(again)
    assert path.read_bytes() == before and path.stat().st_mtime_ns == stamp  # not written again
    assert not any("items.json" in note for note in summary.notes) and summary.reused > 0 and summary.solved == 0


def test_an_item_table_made_from_other_inputs_is_replaced_whole_and_the_run_says_so(again, run):
    path = again.out / "items.json"
    path.write_text('{"version": 1, "count": 0}', encoding="utf-8")  # what another trio's run with other inputs could have left
    summary = rerun(again)
    assert path.read_bytes() == (run.out / "items.json").read_bytes()
    assert any("items.json" in note and "replaced" in note for note in summary.notes), summary.notes
    assert not list(again.out.rglob("*.tmp")) and not [p for p in again.out.iterdir() if p.name.startswith(".")]


def test_a_new_item_table_is_no_cause_for_a_note(tmp_path, run):
    summary = pc.run(SLUG, tmp_path / "fresh", seen_path=run.seen, catalog=run.catalog, processes=1, **NARROW)
    assert not any("items.json" in note for note in summary.notes)
    assert (tmp_path / "fresh" / "items.json").read_bytes() == (run.out / "items.json").read_bytes()


def test_the_item_table_is_written_after_the_files_of_the_trio(again, monkeypatch):
    """The table and the files of the trio are replaced together, or the build can tell (the fingerprints): a table that is replaced last is a table that
    a failed write of the trio's files has not touched."""
    (again.out / "items.json").write_text('{"version": 1, "count": 0}', encoding="utf-8")  # another table: it will be replaced
    real, order = os.replace, []

    def spy(source, target, *args, **kwargs):
        order.append(Path(target).relative_to(again.out).as_posix())
        return real(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", spy)
    rerun(again)
    monkeypatch.undo()
    assert "items.json" in order and order[-1] == "items.json"
    assert order.index(f"{SLUG}/defaults.json") < order.index("items.json")


def test_a_failed_write_of_the_files_of_the_trio_leaves_the_item_table_as_it_was(again, monkeypatch):
    before = b'{"version": 1, "count": 0}'
    (again.out / "items.json").write_bytes(before)

    def failing(*_args, **_kwargs):
        raise OSError("the disk is full")

    monkeypatch.setattr(shards, "write_files", failing)
    with pytest.raises((OSError, pc.PrecomputeError)):
        rerun(again)
    monkeypatch.undo()
    assert (again.out / "items.json").read_bytes() == before  # the table of the other runs is not replaced by a run that did not finish


def test_the_bundle_is_written_with_the_shards_the_defaults_last(again, monkeypatch):
    real, order = os.replace, []

    def spy(source, target, *args, **kwargs):
        order.append(Path(target).relative_to(again.out).as_posix())
        return real(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", spy)
    rerun(again)
    monkeypatch.undo()
    folder = [name for name in order if name.startswith(f"{SLUG}/") and "/runnerups/" not in name]
    assert f"{SLUG}/engine-l50.json" in folder and folder[-1] == f"{SLUG}/defaults.json"
    assert "items.json" not in order  # it was identical: not even replaced


def test_a_table_that_cannot_be_made_takes_the_old_table_away_as_a_bundle_that_cannot_be_made_takes_its_old_bundle(again, monkeypatch):
    """A stale file is not left standing beside new ones: the table is removed, the run says so, and the build says the file is missing."""
    assert (again.out / "items.json").is_file()

    def refusing(*_args, **_kwargs):
        raise ValueError("an item that the tier rules cannot read")

    monkeypatch.setattr(browser, "items", refusing)
    summary = rerun(again)
    monkeypatch.undo()
    assert not (again.out / "items.json").exists()
    assert any("item table" in line for line in summary.violations), summary.violations
    assert any("items.json" in note and "removed" in note for note in summary.notes), summary.notes
    assert (again.dir / "wiki-own.json").is_file()  # the shards are the run's result all the same
    assert "inputs" not in read(again.dir / "engine-l50.json")  # with no table there is no fingerprint to give the bundle: the build refuses it


def test_a_bundle_of_another_level_in_the_trio_folder_is_removed_with_the_other_stale_result_files(again):
    stale = again.dir / "engine-l55.json"
    stale.write_text(json.dumps({"rules_version": RULES.version}), encoding="utf-8")  # (a bundle of an earlier run of these rules: one with no rules version is old, and the run refuses it)
    rerun(again)
    assert not stale.exists() and (again.dir / "engine-l50.json").is_file()


# ---- when the files cannot be made, or the run stops --------------------------------------------------------------------------


def test_a_run_stopped_at_the_limit_writes_neither_file(tmp_path, run):
    summary = pc.run(SLUG, tmp_path / "out", catalog=run.catalog, processes=1, limit=1, **NARROW)
    assert not (tmp_path / "out" / "items.json").exists() and not (tmp_path / "out" / SLUG / "engine-l50.json").exists()
    assert not list((tmp_path / "out" / SLUG).glob("*.json")) and summary.partial is True


def test_a_pool_whose_weapon_setups_depend_on_the_race_is_a_violation_and_writes_no_bundle_but_the_run_goes_on(tmp_path):
    only_trolls = [{**item, "races": ["TRL"]} if item["key"] == "w9014" else item for item in CATALOG]  # a shield one race wears
    catalog = write_catalog(tmp_path / "catalog.json", only_trolls)
    out = tmp_path / "out"
    stale = out / SLUG / "engine-l50.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps({"rules_version": RULES.version}), encoding="utf-8")  # an earlier run's bundle must not be left standing beside new shards (one that records these rules: with none the run refuses it)
    summary = pc.run(SLUG, out, catalog=catalog, processes=1, **NARROW)
    assert (out / SLUG / "wiki-own.json").is_file() and (out / "items.json").is_file()  # the shards and the table are written
    assert not stale.exists()
    assert len(summary.violations) == 1 and "bundle" in summary.violations[0] and "depend on the race" in summary.violations[0]
    assert str(catalog) not in summary.violations[0]


def test_an_item_of_another_class_that_the_tier_rules_cannot_read_is_a_violation_and_writes_no_table_but_the_run_goes_on(tmp_path):
    from test_precompute import make_item

    broken = [*CATALOG, make_item("w9090", "Test Broken Cap", ["HEAD"], classes=["WIZ"], stats={"FOO": 3})]  # not in the pool of the trio
    out = tmp_path / "out"
    summary = pc.run(SLUG, out, catalog=write_catalog(tmp_path / "catalog.json", broken), processes=1, **NARROW)
    assert (out / SLUG / "wiki-own.json").is_file() and (out / SLUG / "engine-l50.json").is_file()
    assert not (out / "items.json").exists()
    assert len(summary.violations) == 1 and "item table" in summary.violations[0] and "FOO" in summary.violations[0]


def test_a_bundle_whose_weapon_setups_differ_from_the_grid_of_the_run_stops_it_before_a_chunk_is_solved(tmp_path, monkeypatch):
    real = browser.bundle

    def lying(*args, **kwargs):
        made = real(*args, **kwargs)
        made["roles"]["tank"]["setups_by_evidence"]["wiki"] = ["dw"]
        return made

    monkeypatch.setattr(browser, "bundle", lying)
    out = tmp_path / "out"
    with pytest.raises(pc.PrecomputeError, match=r"weapon setups.*tank.*wiki"):
        pc.run(SLUG, out, catalog=write_catalog(tmp_path / "catalog.json"), processes=1, **NARROW)
    assert not list(out.rglob("*.json"))  # nothing at all: not a chunk, not a result file


def test_seen_flags_that_cannot_be_read_stop_the_run_before_anything_is_written(tmp_path):
    seen = tmp_path / "seen.json"
    seen.write_text("{}", encoding="utf-8")
    with pytest.raises(pc.PrecomputeError):
        pc.run(SLUG, tmp_path / "out", seen_path=seen, catalog=write_catalog(tmp_path / "catalog.json"), processes=1, **NARROW)
    assert not (tmp_path / "out" / "items.json").exists()


def test_a_catalog_that_changes_while_the_run_starts_is_refused(tmp_path, monkeypatch):
    """The two files and the shards must come from one catalog: what the run reads for the files is checked against what it solves."""
    catalog = write_catalog(tmp_path / "catalog.json")
    real = grid.load_inputs

    def changed_after_reading(*args, **kwargs):
        got = real(*args, **kwargs)
        items = [item for item in CATALOG if item["key"] != "w9014"]  # the file is rebuilt right after the run read it
        write_catalog(catalog, items)
        return got

    monkeypatch.setattr(grid, "load_inputs", changed_after_reading)
    with pytest.raises(pc.PrecomputeError, match="changed"):
        pc.run(SLUG, tmp_path / "out", catalog=catalog, processes=1, **NARROW)
    assert not (tmp_path / "out" / "items.json").exists()


def test_the_module_docstring_and_the_shard_format_document_the_two_files_and_their_fingerprint():
    for text in (pc.__doc__, shards.__doc__):
        assert "engine-l<level>.json" in text and "items.json" in text
    assert "inputs" in shards.__doc__ and "fingerprint" in shards.__doc__ and "fingerprint" in engine_module.__doc__
